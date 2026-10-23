#!/usr/bin/env bash
# Shared helpers for the OPERATOR-side scripts (deploy.sh, stop.sh, start.sh, restore.sh remote).
# They run on your workstation with your own AWS credentials and talk to the host only through
# SSM Run Command (no SSH, no inbound port). Source this file; do not run it.
#
# Environment: CSO_STACK_NAME (default "cso"), AWS_REGION (default us-east-1), AWS_PROFILE as usual.

CSO_STACK_NAME="${CSO_STACK_NAME:-cso}"
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION

stack_output() {
  aws cloudformation describe-stacks --stack-name "$CSO_STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

instance_id() {
  stack_output InstanceId
}

# run_on_host '<command without double quotes or backslashes>'
# Runs the command as root on the host and prints status, stdout and stderr.
run_on_host() {
  local cmd=$1 id params cid
  if [[ $cmd == *\"* || $cmd == *\\* ]]; then
    echo "run_on_host: the command must not contain double quotes or backslashes" >&2
    return 2
  fi
  id=$(instance_id)
  params=$(mktemp)
  printf '{"commands":["%s"]}' "$cmd" >"$params"
  cid=$(aws ssm send-command --instance-ids "$id" --document-name AWS-RunShellScript \
    --parameters "file://$params" --query Command.CommandId --output text)
  rm -f "$params"
  aws ssm wait command-executed --command-id "$cid" --instance-id "$id" || true
  aws ssm get-command-invocation --command-id "$cid" --instance-id "$id" \
    --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
  [[ $(aws ssm get-command-invocation --command-id "$cid" --instance-id "$id" \
    --query Status --output text) == Success ]]
}
