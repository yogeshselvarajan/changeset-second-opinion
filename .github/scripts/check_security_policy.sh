#!/usr/bin/env bash
# Cross checks that the security policy and the files that point at it agree. Run from the repository root.
#  - SECURITY.md exists and names a contact address
#  - the same address is the package author address (what PyPI shows)
#  - CODEOWNERS requires the owner's review for SECURITY.md
#  - CONTRIBUTING.md or README.md points readers at SECURITY.md
#  - the issue chooser offers private reporting
#  - no workflow checks out pull request code under pull_request_target
set -euo pipefail

fail=0
problem() { echo "::error::$1"; fail=1; }

[ -f SECURITY.md ] || { echo "::error::SECURITY.md is missing"; exit 1; }
email="$(grep -oE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' SECURITY.md | head -n 1 || true)"
[ -n "$email" ] || problem "SECURITY.md names no contact address"

if [ -n "$email" ] && ! grep -q "$email" backend/pyproject.toml; then
  problem "the contact address in SECURITY.md ($email) is not the author address in backend/pyproject.toml"
fi
grep -q '^/SECURITY.md' .github/CODEOWNERS || problem "CODEOWNERS has no line for /SECURITY.md"
grep -qE 'SECURITY\.md' CONTRIBUTING.md README.md 2>/dev/null || problem "neither CONTRIBUTING.md nor README.md points at SECURITY.md"
grep -q 'security/advisories' .github/ISSUE_TEMPLATE/config.yml || problem "the issue chooser has no link to private security reporting"

for wf in .github/workflows/*.yml; do
  if grep -q 'pull_request_target' "$wf" && grep -q 'actions/checkout' "$wf"; then
    problem "$wf uses pull_request_target and checks out code"
  fi
done

if [ "$fail" -eq 0 ]; then echo "security policy cross check passed"; fi
exit "$fail"
