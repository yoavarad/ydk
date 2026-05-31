#!/bin/sh
# Enforcement: detect wildcard IAM principals
# Wildcard principals in assume_role_policy allow any AWS entity to assume the role.

set -eu

PROJECT_ROOT="${ODK_PROJECT_ROOT:-$(pwd)}"

echo "Checking for wildcard IAM principals..."

MATCHES=$(grep -rn 'Principal.*\*' "$PROJECT_ROOT" --include="*.tf" 2>/dev/null | grep -E "(assume_role_policy|Principal)" || true)

if [ -n "$MATCHES" ]; then
  echo "FAIL: Found wildcard IAM principals:"
  echo "$MATCHES"
  echo ""
  echo "Wildcard principals (\"*\") allow any entity to assume a role or access a resource."
  echo "Restrict principals to specific AWS accounts, services, or ARNs."
  exit 1
fi

echo "PASS: No wildcard IAM principals found."
exit 0
