#!/usr/bin/env bash
# Uploads a test image and tails the results. Reads bucket/table names from
# terraform outputs, so run it from the repo root after `make deploy`.
set -euo pipefail

PROJECT="${PROJECT:-cloudsight-intake}"
IMAGE="${1:-test/sample-image.jpg}"

INPUT_BUCKET="$(terraform -chdir=terraform output -raw input_bucket)"
TABLE="$(terraform -chdir=terraform output -raw dynamodb_table)"

[ -f "$IMAGE" ] || { echo "Test image not found: $IMAGE" >&2; exit 1; }

KEY="uploads/test-$(date +%s)-$(basename "$IMAGE")"
echo "Uploading $IMAGE -> s3://$INPUT_BUCKET/$KEY"
aws s3 cp "$IMAGE" "s3://$INPUT_BUCKET/$KEY"

echo
echo "Tailing Lambda logs (Ctrl-C to stop)..."
aws logs tail "/aws/lambda/${PROJECT}-processor" --follow --since 1m &
TAIL_PID=$!
sleep 20
kill "$TAIL_PID" 2>/dev/null || true

echo
echo "DynamoDB rows:"
aws dynamodb scan --table-name "$TABLE" \
  --query 'Items[].{image_id:image_id.S,status:status.S,summary:summary.S}' --output table
