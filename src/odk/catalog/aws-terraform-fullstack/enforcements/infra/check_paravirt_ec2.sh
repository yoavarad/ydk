#!/bin/sh
# Enforcement: detect paravirtualized EC2 instance types
# Paravirtualized instances (t1.*, m1.*, c1.*, m2.*) are legacy and lack
# security features available in HVM instances.

set -eu

PROJECT_ROOT="${ODK_PROJECT_ROOT:-$(pwd)}"

echo "Checking for paravirtualized EC2 instance types..."

MATCHES=$(grep -rn 'instance_type.*=.*"\(t1\.\|m1\.\|c1\.\|m2\.\)' "$PROJECT_ROOT" --include="*.tf" 2>/dev/null || true)

if [ -n "$MATCHES" ]; then
  echo "FAIL: Found paravirtualized EC2 instance types:"
  echo "$MATCHES"
  echo ""
  echo "These instance types use paravirtualization and lack modern security features."
  echo "Use HVM-based instance types (t3.*, m5.*, c5.*, etc.) instead."
  exit 1
fi

echo "PASS: No paravirtualized instance types found."
exit 0
