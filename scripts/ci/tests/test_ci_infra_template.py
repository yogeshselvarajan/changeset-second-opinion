"""The host template keeps the promises of the operations work without a deploy.

cfn-lint checks that the template is valid; these tests check what it must never become: a host with
an open SSH port, a secret in user data, a role that can read all of S3, or alarms that stopped
pointing at the one topic.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip("yaml")


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps CloudFormation's short tags (!Ref, !Sub ...) as plain values."""


def _tag(loader: Any, suffix: str, node: Any) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return {suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {suffix: loader.construct_sequence(node, deep=True)}
    return {suffix: loader.construct_mapping(node, deep=True)}


_Loader.add_multi_constructor("!", _tag)


@pytest.fixture
def template(repo_root: Path) -> dict[str, Any]:
    text = (repo_root / "infra" / "cloudformation" / "cso-single-host.yaml").read_text("utf-8")
    return yaml.load(text, Loader=_Loader)  # noqa: S506 (a safe loader subclass)


def _resources(template: dict[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in template["Resources"].items() if v["Type"] == kind}


def _statements(template: dict[str, Any]) -> list[dict[str, Any]]:
    role = template["Resources"]["InstanceRole"]["Properties"]
    return role["Policies"][0]["PolicyDocument"]["Statement"]


def test_the_only_inbound_port_is_https(template: dict[str, Any]) -> None:
    ingress = template["Resources"]["HostSecurityGroup"]["Properties"]["SecurityGroupIngress"]
    assert [(rule["FromPort"], rule["ToPort"]) for rule in ingress] == [(443, 443)]


def test_the_host_has_no_key_pair_and_uses_session_manager(template: dict[str, Any]) -> None:
    host = template["Resources"]["Host"]["Properties"]
    assert "KeyName" not in host
    assert "KeyName" not in template["Parameters"]
    role = template["Resources"]["InstanceRole"]["Properties"]
    assert "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore" in role["ManagedPolicyArns"]
    assert host["MetadataOptions"]["HttpTokens"] == "required"


def test_user_data_carries_no_secret(template: dict[str, Any]) -> None:
    user_data = template["Resources"]["Host"]["Properties"]["UserData"]["Fn::Base64"]["Sub"]
    assert "--with-decryption" in user_data  # only the optional deploy token, held in a variable
    assert user_data.count("--with-decryption") == 1
    for forbidden in ("client_secret", "SESSION_SECRET", "password", "AKIA"):
        assert forbidden.lower() not in user_data.lower()
    assert "/cso/${Stage}/git_token" in user_data


def test_secrets_are_read_from_the_stage_path_only(template: dict[str, Any]) -> None:
    ssm = [s for s in _statements(template) if "ssm:GetParameter" in s["Action"]]
    assert len(ssm) == 1
    assert ssm[0]["Resource"] == {
        "Sub": "arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/cso/${Stage}/*"
    }
    decrypt = [s for s in _statements(template) if s["Action"] == ["kms:Decrypt"]]
    assert len(decrypt) == 1
    assert "kms:ViaService" in decrypt[0]["Condition"]["StringEquals"]


def test_the_role_reaches_only_its_own_bucket_prefixes(template: dict[str, Any]) -> None:
    for statement in _statements(template):
        actions = statement["Action"]
        for action in actions:
            if action.startswith("s3:"):
                resource = str(statement["Resource"])
                assert "BackupBucket" in resource, statement
                assert "*" not in resource.replace("/backups/*", "").replace("/litestream/*", "")
    all_actions = {a for s in _statements(template) for a in s["Action"]}
    assert "s3:*" not in all_actions and "ssm:*" not in all_actions


def test_the_backup_bucket_is_private_versioned_and_kept(template: dict[str, Any]) -> None:
    bucket = template["Resources"]["BackupBucket"]
    assert bucket["DeletionPolicy"] == "Retain"
    props = bucket["Properties"]
    assert props["VersioningConfiguration"]["Status"] == "Enabled"
    assert all(props["PublicAccessBlockConfiguration"].values())
    rules = {r["Prefix"]: r for r in props["LifecycleConfiguration"]["Rules"]}
    assert rules["litestream/"]["NoncurrentVersionExpiration"]["NoncurrentDays"] == 30


def test_snapshots_run_nightly_and_keep_seven(template: dict[str, Any]) -> None:
    policy = _resources(template, "AWS::DLM::LifecyclePolicy")
    assert len(policy) == 1
    schedule = next(iter(policy.values()))["Properties"]["PolicyDetails"]["Schedules"][0]
    assert schedule["CreateRule"]["Interval"] == 24
    assert schedule["RetainRule"]["Count"] == 7


def test_every_alarm_notifies_the_one_topic(template: dict[str, Any]) -> None:
    alarms = _resources(template, "AWS::CloudWatch::Alarm")
    assert {
        "StatusCheckAlarm",
        "BackupFailedAlarm",
        "Http5xxRatioAlarm",
        "ReadyzFailingAlarm",
        "DiskUsedAlarm",
        "GpuMemoryAlarm",
    } <= set(alarms)
    for name, alarm in alarms.items():
        assert alarm["Properties"]["AlarmActions"] == [{"Ref": "AlertTopic"}], name
    assert alarms["GpuMemoryAlarm"]["Condition"] == "HasGpu"
    assert alarms["Http5xxRatioAlarm"]["Properties"]["Threshold"] == 5
    assert alarms["DiskUsedAlarm"]["Properties"]["Threshold"] == 80
    assert alarms["GpuMemoryAlarm"]["Properties"]["Threshold"] == 90


def test_logs_are_kept_fourteen_days(template: dict[str, Any]) -> None:
    group = template["Resources"]["AppLogGroup"]["Properties"]
    assert group["RetentionInDays"] == 14


def test_the_budget_warns_at_twenty_and_fifty_dollars(template: dict[str, Any]) -> None:
    budget = template["Resources"]["MonthlyBudget"]["Properties"]["NotificationsWithSubscribers"]
    absolute = {
        n["Notification"]["Threshold"]
        for n in budget
        if n["Notification"]["ThresholdType"] == "ABSOLUTE_VALUE"
    }
    assert absolute == {20, 50}


def test_nothing_secret_is_written_to_the_disk_by_the_boot_scripts(repo_root: Path) -> None:
    scripts = repo_root / "infra" / "scripts"
    bootstrap = (scripts / "bootstrap.sh").read_text("utf-8")
    boot = (scripts / "boot.sh").read_text("utf-8")
    # the client secret is never read with decryption by bootstrap, and boot.sh writes only to /run
    assert not re.search(r"osm_oauth_client_secret.*--with-decryption", bootstrap)
    assert "CSO_OSM_OAUTH_CLIENT_SECRET" not in bootstrap
    assert "dir=/run/cso" in boot and "/opt/cso/.env" not in boot
    assert "umask 077" in boot


def test_compose_reads_secrets_from_the_tmpfs_file_only(repo_root: Path) -> None:
    compose = (repo_root / "infra" / "compose" / "docker-compose.aws.yml").read_text("utf-8")
    assert "path: /run/cso/secrets.env" in compose
    assert "litestream/litestream:0.3.13" in compose  # pinned, never :latest
