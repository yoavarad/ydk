#!/bin/sh
# Enforcement: detect AMI usage without owner restrictions
# Using AMIs without owner restrictions can lead to running untrusted images.

set -eu

PROJECT_ROOT="${ODK_PROJECT_ROOT:-$(pwd)}"

echo "Checking for AMI references without owner restrictions..."

ERRORS=0

# Find hardcoded ami- references not inside a data source with owners
AMI_REFS=$(grep -rn 'ami-[0-9a-f]\{8,17\}' "$PROJECT_ROOT" --include="*.tf" 2>/dev/null || true)

if [ -n "$AMI_REFS" ]; then
  # Check if there are data "aws_ami" blocks with owners specified
  HAS_DATA_AMI=$(grep -rl 'data "aws_ami"' "$PROJECT_ROOT" --include="*.tf" 2>/dev/null || true)

  if [ -z "$HAS_DATA_AMI" ]; then
    echo "WARN: Found hardcoded AMI IDs without data source lookups:"
    echo "$AMI_REFS"
    echo ""
    echo "Consider using data \"aws_ami\" with owners = [\"amazon\", \"self\"] for verified images."
  fi
fi

# Check data "aws_ami" blocks without owners
DATA_AMI_FILES=$(grep -rln 'data "aws_ami"' "$PROJECT_ROOT" --include="*.tf" 2>/dev/null || true)

if [ -n "$DATA_AMI_FILES" ]; then
  for f in $DATA_AMI_FILES; do
    # Check if the file has owners specified
    if ! grep -q 'owners' "$f" 2>/dev/null; then
      echo "FAIL: $f has data \"aws_ami\" without owners restriction."
      echo "Add: owners = [\"amazon\", \"self\"] to restrict to trusted AMI sources."
      ERRORS=$((ERRORS + 1))
    fi
  done
fi

if [ $ERRORS -gt 0 ]; then
  echo "FAIL: $ERRORS AMI source(s) missing owner restrictions."
  exit 1
fi

echo "PASS: AMI usage checks passed."
exit 0
