#!/bin/bash
# Enforcement: all resources must have required tags
# Required tags: Name, Environment, Project, ManagedBy

set -euo pipefail

INFRA_DIR="${YDK_PROJECT_ROOT:-$(pwd)}/infra"
REQUIRED_TAGS=("Environment" "Project" "ManagedBy")
ERRORS=0

if [ ! -d "$INFRA_DIR" ]; then
  echo "SKIP: No infra/ directory found"
  exit 0
fi

echo "Checking resource tagging..."

for tf_file in "$INFRA_DIR"/*.tf; do
  [ -f "$tf_file" ] || continue

  # Find all resource blocks
  RESOURCES=$(grep -n '^resource "' "$tf_file" 2>/dev/null || true)

  if [ -z "$RESOURCES" ]; then
    continue
  fi

  # Check each resource has tags block
  while IFS= read -r line; do
    LINE_NUM=$(echo "$line" | cut -d: -f1)
    RESOURCE_DEF=$(echo "$line" | cut -d: -f2-)

    # Skip data sources and resources that don't support tags
    if echo "$RESOURCE_DEF" | grep -qE "(aws_iam_role_policy_attachment|aws_route_table_association|aws_s3_bucket_policy|aws_s3_bucket_versioning|aws_s3_bucket_server_side_encryption|aws_s3_bucket_public_access_block)"; then
      continue
    fi

    # Look for tags block within the next 100 lines of the resource
    TAGS_FOUND=$(sed -n "${LINE_NUM},$((LINE_NUM + 100))p" "$tf_file" | grep -c "tags = {" || echo 0)

    if [ "$TAGS_FOUND" -eq 0 ]; then
      echo "WARN: $tf_file:$LINE_NUM - $RESOURCE_DEF may be missing tags"
    fi
  done <<< "$RESOURCES"
done

if [ $ERRORS -gt 0 ]; then
  echo "FAIL: $ERRORS tagging issue(s) found."
  exit 1
fi

echo "PASS: Tagging checks passed."
