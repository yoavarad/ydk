#!/bin/sh
# Enforcement: detect Glacier vault public access
# Glacier vaults with wildcard principals in access policies are publicly accessible.

set -eu

PROJECT_ROOT="${ODK_PROJECT_ROOT:-$(pwd)}"

echo "Checking for Glacier vault public access..."

MATCHES=$(grep -rn 'aws_glacier_vault' "$PROJECT_ROOT" --include="*.tf" -A 20 2>/dev/null | grep -E "(access_policy|Principal)" | grep '\*' || true)

if [ -n "$MATCHES" ]; then
  echo "FAIL: Found Glacier vault with public access policy:"
  echo "$MATCHES"
  echo ""
  echo "Restrict Glacier vault access_policy principals to specific accounts/roles."
  exit 1
fi

echo "PASS: No public Glacier vault access detected."
exit 0
