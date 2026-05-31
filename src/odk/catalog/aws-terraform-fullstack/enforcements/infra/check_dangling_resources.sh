#!/bin/sh
# Enforcement: detect dangling Route53 and CloudFront origins
# Dangling DNS records and origins can be hijacked by attackers.

set -eu

PROJECT_ROOT="${ODK_PROJECT_ROOT:-$(pwd)}"

echo "Checking for dangling Route53 and CloudFront resources..."

ERRORS=0

# Check for Route53 alias records pointing to S3 buckets not defined in code
ALIAS_S3=$(grep -rn 'alias' "$PROJECT_ROOT" --include="*.tf" -A 5 2>/dev/null | grep -i 's3' || true)

if [ -n "$ALIAS_S3" ]; then
  # Extract S3 bucket names from alias targets
  ALIAS_BUCKETS=$(echo "$ALIAS_S3" | grep -oE '[a-z0-9][a-z0-9.-]*\.s3[a-z0-9.-]*\.amazonaws\.com' 2>/dev/null || true)

  if [ -n "$ALIAS_BUCKETS" ]; then
    for bucket_domain in $ALIAS_BUCKETS; do
      bucket_name=$(echo "$bucket_domain" | sed 's/\.s3.*//')
      # Check if this bucket is defined as a resource
      if ! grep -rq "bucket.*=.*\"$bucket_name\"" "$PROJECT_ROOT" --include="*.tf" 2>/dev/null; then
        if ! grep -rq "resource \"aws_s3_bucket\" \"$bucket_name\"" "$PROJECT_ROOT" --include="*.tf" 2>/dev/null; then
          echo "WARN: Route53 alias points to S3 bucket '$bucket_name' which may not be defined in code."
          ERRORS=$((ERRORS + 1))
        fi
      fi
    done
  fi
fi

# Check for CloudFront origins pointing to undefined resources
CF_ORIGINS=$(grep -rn 'origin' "$PROJECT_ROOT" --include="*.tf" -A 10 2>/dev/null | grep 'domain_name' || true)

if [ -n "$CF_ORIGINS" ]; then
  # Look for hardcoded domain names (not references to other resources)
  HARDCODED_ORIGINS=$(echo "$CF_ORIGINS" | grep -E '"[^"]*\.(s3|elb|execute-api)[^"]*\.amazonaws\.com"' || true)

  if [ -n "$HARDCODED_ORIGINS" ]; then
    echo "WARN: CloudFront origins with hardcoded AWS domains (should reference resources):"
    echo "$HARDCODED_ORIGINS"
    echo ""
    echo "Use resource references (e.g., aws_s3_bucket.x.bucket_regional_domain_name) instead."
    ERRORS=$((ERRORS + 1))
  fi
fi

if [ $ERRORS -gt 0 ]; then
  echo "FAIL: $ERRORS potential dangling resource reference(s) found."
  exit 1
fi

echo "PASS: No dangling resource references detected."
exit 0
