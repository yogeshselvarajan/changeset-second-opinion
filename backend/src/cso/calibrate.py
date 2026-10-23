"""Run a calibration: read the reviewers' outcomes, report what would change, apply on request.

Applying never edits an existing configuration. It writes an immutable calibration row and stores a
new configuration version (the pack's own YAML plus the fitted `panel.probe_thresholds` and a
`calibration` reference), then makes that version active. Runs already made keep the version they
used, and every receipt names the version it ran with.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.calibration import CalibrationReport, build_report
from cso.domain.config import CommunityConfig, ConfigError
from cso.domain.enums import Disposition
from cso.domain.panel import FactPanel
from cso.persistence.db import session_scope
from cso.persistence.repos import AuditRepo, CalibrationsRepo, ConfigsRepo, OutcomesRepo
from cso.persistence.repos._common import utcnow


class UnknownPackError(ValueError):
    """The named pack is not among the pack files."""


@dataclass(frozen=True)
class CalibrationRun:
    """A dry run (`applied` False) or an applied calibration."""

    pack_id: str
    report: CalibrationReport
    applied: bool
    calibration_id: str | None = None
    config_version: str | None = None
    reason: str | None = None


def _readings(receipt: dict[str, Any] | None) -> dict[str, tuple[float, str]] | None:
    """`probe: (probability, state)` from a stored receipt, or None without a readable panel."""
    if not receipt or not receipt.get("panel"):
        return None
    try:
        panel = FactPanel.model_validate(receipt["panel"])
    except ValidationError:
        return None
    return {i: (r.probability, r.state.value) for i, r in panel.readings.items()}


async def active_pack_id(session: AsyncSession) -> str:
    """The pack the active configuration belongs to; the default pack when nothing is stored."""
    row = await ConfigsRepo(session).get_active()
    if row is None:
        return CommunityConfig.load().pack_id
    if row.pack_id:
        return row.pack_id
    return CommunityConfig.from_yaml_text(row.yaml, source=f"stored config {row.version}").pack_id


def effective_yaml(pack_text: str, thresholds: dict[str, tuple[float, float]], cal_id: str) -> str:
    """The pack's YAML with the fitted cut points and the calibration reference added."""
    data = yaml.safe_load(pack_text)
    panel = data.setdefault("panel", {})
    panel["probe_thresholds"] = {
        probe: {"low": low, "high": high} for probe, (low, high) in sorted(thresholds.items())
    }
    data["calibration"] = {"id": cal_id}
    return str(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def _calibration_id(pack_id: str, thresholds: dict[str, tuple[float, float]], at: datetime) -> str:
    digest = hashlib.sha256(
        json.dumps([pack_id, sorted(thresholds.items())], separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:8]
    return f"cal-{at:%Y%m%d%H%M%S}-{digest}"


async def run_calibration(
    factory: async_sessionmaker[AsyncSession],
    *,
    pack_id: str | None,
    apply: bool,
    actor: str,
    now: datetime | None = None,
) -> CalibrationRun:
    """Report what the outcomes say about a pack's cut points, and apply it when asked.

    Raises `UnknownPackError` for a pack with no file. Applying with nothing to change is a no-op
    that says why.
    """
    stamp = now or utcnow()
    try:
        packs = CommunityConfig.load_all_with_text()
    except ConfigError as exc:
        raise UnknownPackError(str(exc)) from exc
    async with session_scope(factory) as session:
        chosen = pack_id or await active_pack_id(session)
        if chosen not in packs:
            raise UnknownPackError(chosen)
        config, text = packs[chosen]
        defaults = {
            probe: (config.panel.thresholds.low, config.panel.thresholds.high)
            for probe in config.panel.noul_ids
        }
        configs = ConfigsRepo(session)
        pack_of: dict[str, str | None] = {}
        counted: list[tuple[Disposition, dict[str, tuple[float, str]], Any, str | None]] = []
        for outcome, run in await OutcomesRepo(session).latest_per_case():
            if run.config_version not in pack_of:
                stored = await configs.get(run.config_version)
                pack_of[run.config_version] = stored.pack_id if stored else None
            if pack_of[run.config_version] not in (None, chosen):
                continue  # a run made under another pack says nothing about this one
            readings = _readings(run.receipt)
            if readings is None:
                continue
            counted.append((outcome.disposition, readings, outcome.probe_corrections, run.band))
        report = build_report(counted, defaults)
        changed = report.changed
        if not apply:
            return CalibrationRun(pack_id=chosen, report=report, applied=False)
        if not changed:
            return CalibrationRun(
                pack_id=chosen,
                report=report,
                applied=False,
                reason="No probe has enough labelled readings to change its cut points.",
            )
        cal_id = _calibration_id(chosen, changed, stamp)
        effective = CommunityConfig.from_yaml_text(
            effective_yaml(text, changed, cal_id), source=f"calibrated {chosen}"
        )
        effective_text = effective_yaml(text, changed, cal_id)
        await CalibrationsRepo(session).add(
            calibration_id=cal_id,
            pack_id=chosen,
            n_outcomes=report.n_labelled_outcomes,
            thresholds={p: {"low": lo, "high": hi} for p, (lo, hi) in changed.items()},
            band_report=[
                {
                    "band": b.band,
                    "n": b.n,
                    "correct": b.accuracy.correct,
                    "decided": b.accuracy.decided,
                    "lower": b.accuracy.lower,
                    "upper": b.accuracy.upper,
                    "status": b.status,
                }
                for b in report.bands
            ],
            created_by=actor,
            now=stamp,
        )
        await configs.add_if_absent(effective, effective_text, activate=True, now=stamp)
        await AuditRepo(session).append(
            actor=actor,
            action="config.calibration_applied",
            payload={
                "pack_id": chosen,
                "calibration_id": cal_id,
                "config_version": effective.version,
                "probes": sorted(changed),
            },
            now=stamp,
        )
    return CalibrationRun(
        pack_id=chosen,
        report=report,
        applied=True,
        calibration_id=cal_id,
        config_version=effective.version,
    )
