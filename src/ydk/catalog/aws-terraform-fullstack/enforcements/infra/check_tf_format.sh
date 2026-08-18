#!/bin/bash
# Enforcement: check that all .tf files are properly formatted
# Requires: terraform CLI installed

set -euo pipefail

INFRA_DIR="${YDK_PROJECT_ROOT:-$(pwd)}/infra"

if [ ! -d "$INFRA_DIR" ]; then
  echo "SKIP: No infra/ directory found"
  exit 0
fi

if ! command -v terraform &>/dev/null; then
  echo "WARN: terraform not installed, skipping format check"
  exit 0
fi

echo "Checking Terraform formatting..."

UNFORMATTED=$(terraform fmt -check -recursive -diff "$INFRA_DIR" 2>&1 || true)

if [ -n "$UNFORMATTED" ]; then
  echo "FAIL: The following files are not properly formatted:"
  echo "$UNFORMATTED"
  echo ""
  echo "Run 'terraform fmt -recursive infra/' to fix."
  exit 1
fi

echo "PASS: All .tf files are properly formatted."
