#!/usr/bin/env bash
# Build and deploy the serverless replay demo (SPIKE, never run against AWS yet).
#   CERT_ARN=arn:aws:acm:us-east-1:... ALERT_EMAIL=you@example.com bash infra/aws-serverless-demo/deploy.sh
# Needs: aws CLI with credentials for us-east-1, docker with buildx. Run from anywhere in the repo.
# Optional: STACK (cso-demo), DOMAIN (osm.changesetreview.online), APEX (empty), BUDGET_USD (5).
set -euo pipefail

: "${CERT_ARN:?set CERT_ARN to the ISSUED us-east-1 ACM certificate}"
: "${ALERT_EMAIL:?set ALERT_EMAIL}"
REGION=us-east-1
STACK="${STACK:-cso-demo}"
DOMAIN="${DOMAIN:-osm.changesetreview.online}"
APEX="${APEX:-}"
BUDGET_USD="${BUDGET_USD:-5}"
REPO=cso-lwa-api
cd "$(git rev-parse --show-toplevel)"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
TAG="$(git rev-parse --short HEAD)-$(date +%Y%m%d%H%M%S)"

echo "== 1/5 image repository"
if ! aws ecr describe-repositories --region "$REGION" --repository-names "$REPO" >/dev/null 2>&1; then
  aws ecr create-repository --region "$REGION" --repository-name "$REPO" \
    --image-tag-mutability IMMUTABLE --image-scanning-configuration scanOnPush=true >/dev/null
  aws ecr put-lifecycle-policy --region "$REGION" --repository-name "$REPO" --lifecycle-policy-text \
    '{"rules":[{"rulePriority":1,"description":"keep 3","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":3},"action":{"type":"expire"}}]}' >/dev/null
fi

echo "== 2/5 build and push the x86_64 API image (builds natively on a PC, no emulation)"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
# provenance and sbom off: Lambda rejects an image index with attestations.
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  -f infra/aws-serverless-demo/Dockerfile -t "${REGISTRY}/${REPO}:${TAG}" --push .
DIGEST="$(aws ecr describe-images --region "$REGION" --repository-name "$REPO" \
  --image-ids imageTag="$TAG" --query 'imageDetails[0].imageDigest' --output text)"
IMAGE_URI="${REGISTRY}/${REPO}@${DIGEST}"

echo "== 3/5 stack"
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file infra/aws-serverless-demo/template.yaml --no-fail-on-empty-changeset \
  --capabilities CAPABILITY_IAM --tags project=cso-demo \
  --parameter-overrides "DomainName=${DOMAIN}" "ApexDomain=${APEX}" "CertificateArn=${CERT_ARN}" \
    "ImageUri=${IMAGE_URI}" "AlertEmail=${ALERT_EMAIL}" "MonthlyBudgetUsd=${BUDGET_USD}"
out() { aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
BUCKET="$(out BucketName)"; DIST_ID="$(out DistributionId)"

echo "== 4/5 web app and docs (built by the existing web image recipe, nothing is changed there)"
docker build --target web -f infra/compose/web.Dockerfile -t cso-lwa-webbuild \
  --build-arg "CSO_PUBLIC_ORIGIN=https://${DOMAIN}" .
CID="$(docker create cso-lwa-webbuild)"
WORK="$(mktemp -d)"
trap 'docker rm -f "$CID" >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
# Git Bash on Windows hands Docker and the AWS CLI a path they cannot read; cygpath gives the Windows form.
if command -v cygpath >/dev/null 2>&1; then WORK="$(cygpath -m "$WORK")"; fi
docker cp "${CID}:/web/dist" "${WORK}/dist"
# Hashed assets: one year. Everything else: revalidate each time (as Caddy does).
aws s3 sync "${WORK}/dist" "s3://${BUCKET}" --delete --exclude 'assets/*' --exclude 'docs/_astro/*' \
  --cache-control 'no-cache'
aws s3 sync "${WORK}/dist/assets" "s3://${BUCKET}/assets" --delete --cache-control 'public, max-age=31536000, immutable'
[ -d "${WORK}/dist/docs/_astro" ] && aws s3 sync "${WORK}/dist/docs/_astro" "s3://${BUCKET}/docs/_astro" \
  --delete --cache-control 'public, max-age=31536000, immutable'

echo "== 5/5 invalidate"
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths '/*' >/dev/null
echo "Done. Point the CNAME of ${DOMAIN} at: $(out DistributionDomain)"
