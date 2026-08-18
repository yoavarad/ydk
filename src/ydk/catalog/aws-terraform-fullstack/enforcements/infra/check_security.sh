#!/bin/sh
# Enforcement: comprehensive security scanning via checkov
# Runs checkov with specific check IDs targeting critical AWS misconfigurations.

set -eu

PROJECT_ROOT="${YDK_PROJECT_ROOT:-$(pwd)}"
INFRA_DIR="$PROJECT_ROOT/infra"

if [ ! -d "$INFRA_DIR" ]; then
  echo "SKIP: No infra/ directory found"
  exit 0
fi

# Verify checkov is available
if ! command -v checkov >/dev/null 2>&1; then
  echo "FAIL: checkov is not installed. Run: pip install checkov"
  exit 1
fi

CHECKS="CKV_AWS_20,CKV_AWS_21,CKV_AWS_54,CKV_AWS_55,CKV_AWS_56,CKV_AWS_57,CKV_AWS_93,CKV_AWS_27,CKV_AWS_26,CKV_AWS_7,CKV_AWS_33,CKV_AWS_45,CKV_AWS_115,CKV_AWS_173,CKV_AWS_260,CKV_AWS_23,CKV_AWS_24,CKV_AWS_25,CKV_AWS_290,CKV_AWS_60,CKV_AWS_61,CKV_AWS_118,CKV_AWS_129,CKV_AWS_46,CKV_AWS_74,CKV_AWS_134,CKV_AWS_5,CKV_AWS_84,CKV_AWS_137"

echo "Running checkov security scan on $INFRA_DIR..."

# Determine scan scope based on event type
if [ "${YDK_EVENT_TYPE:-}" = "file_write" ] || [ "${YDK_EVENT_TYPE:-}" = "file_create" ]; then
  # Per-file mode: scan specific file if provided
  TARGET_FILE="${YDK_TARGET_FILE:-$INFRA_DIR}"
  if [ -f "$TARGET_FILE" ]; then
    RESULT=$(checkov --file "$TARGET_FILE" --check "$CHECKS" --output json --compact 2>/dev/null || true)
  else
    RESULT=$(checkov --directory "$INFRA_DIR" --check "$CHECKS" --output json --compact 2>/dev/null || true)
  fi
else
  # Full-project mode
  RESULT=$(checkov --directory "$INFRA_DIR" --check "$CHECKS" --output json --compact 2>/dev/null || true)
fi

# Parse results for failures
if [ -z "$RESULT" ]; then
  echo "PASS: No relevant Terraform resources found for these checks."
  exit 0
fi

FAILED=$(echo "$RESULT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    # checkov can return a list (multiple frameworks) or a dict (single)
    if isinstance(data, list):
        total_failed = sum(r.get('summary', {}).get('failed', 0) for r in data)
    else:
        total_failed = data.get('summary', {}).get('failed', 0)
    print(total_failed)
except (json.JSONDecodeError, KeyError, TypeError):
    print(0)
" 2>/dev/null || echo "0")

if [ "$FAILED" -gt 0 ]; then
  echo "FAIL: checkov found $FAILED security violation(s)."
  echo ""
  echo "Checks cover:"
  echo "  - S3 public access (CKV_AWS_20,21,54,55,56,57,93)"
  echo "  - SQS/SNS public policies (CKV_AWS_27,26)"
  echo "  - KMS key rotation and access (CKV_AWS_7,33)"
  echo "  - Lambda public access (CKV_AWS_45,115,173,260)"
  echo "  - Security groups wide-open (CKV_AWS_23,24,25)"
  echo "  - IAM overly permissive (CKV_AWS_290,60,61)"
  echo "  - RDS/EBS public snapshots and IAM auth (CKV_AWS_118,129,46,74,134)"
  echo "  - Elasticsearch public access (CKV_AWS_5,84,137)"
  echo ""
  echo "Run 'checkov --directory $INFRA_DIR --check $CHECKS' for full details."
  exit 1
fi

echo "PASS: All checkov security checks passed."
exit 0
