#!/usr/bin/env bash
# End-to-end functional test for CloudSight Intake.
#
#   ./scripts/smoke-test.sh [path/to/image.jpg]
#
# Reads Terraform outputs, uploads an image, waits for the Lambda to write a
# DynamoDB row + results JSON, tails recent logs, and checks the SNS email
# subscription is confirmed. Needs AWS credentials in the environment.
set -euo pipefail

IMAGE="${1:-test/sample-image.jpg}"
TF="terraform -chdir=terraform"
TIMEOUT="${TIMEOUT:-90}"

command -v aws >/dev/null || { echo "aws CLI not found"; exit 1; }
[ -f "$IMAGE" ] || { echo "image not found: $IMAGE"; exit 1; }

echo "==> Reading Terraform outputs"
INPUT_BUCKET=$($TF output -raw input_bucket)
OUTPUT_BUCKET=$($TF output -raw output_bucket)
TABLE=$($TF output -raw dynamodb_table)
TOPIC_ARN=$($TF output -raw sns_topic_arn)
FN=$($TF output -raw lambda_function_name)
printf '    input=%s\n    output=%s\n    table=%s\n    fn=%s\n' \
  "$INPUT_BUCKET" "$OUTPUT_BUCKET" "$TABLE" "$FN"

echo "==> Checking SNS email subscription"
PENDING=$(aws sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN" \
  --query "length(Subscriptions[?SubscriptionArn=='PendingConfirmation'])" --output text)
CONFIRMED=$(aws sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN" \
  --query "length(Subscriptions[?SubscriptionArn!='PendingConfirmation' && Protocol=='email'])" --output text)
if [ "${CONFIRMED:-0}" -gt 0 ]; then
  echo "    OK - $CONFIRMED confirmed email subscription(s)"
elif [ "${PENDING:-0}" -gt 0 ]; then
  echo "    WARNING - subscription is PendingConfirmation."
  echo "    Open the 'AWS Notification - Subscription Confirmation' email and click the link,"
  echo "    or: aws sns confirm-subscription --topic-arn $TOPIC_ARN --token <TOKEN-from-email>"
else
  echo "    WARNING - no email subscription found on the topic."
fi

# ETag of a single-part PUT == MD5 of the bytes.
if command -v md5sum >/dev/null; then ETAG=$(md5sum "$IMAGE" | awk '{print $1}')
else ETAG=$(md5 -q "$IMAGE"); fi
KEY="uploads/smoke-$(date +%s)-$(basename "$IMAGE")"

echo "==> Uploading s3://$INPUT_BUCKET/$KEY  (image_id=$ETAG)"
aws s3api put-object --bucket "$INPUT_BUCKET" --key "$KEY" \
  --body "$IMAGE" --content-type image/jpeg >/dev/null

echo "==> Waiting up to ${TIMEOUT}s for the DynamoDB row"
ROW=""
for _ in $(seq 1 "$((TIMEOUT / 3))"); do
  ROW=$(aws dynamodb query --table-name "$TABLE" \
    --key-condition-expression 'image_id = :id' \
    --expression-attribute-values "{\":id\":{\"S\":\"$ETAG\"}}" \
    --query 'Items[0]' --output json 2>/dev/null || true)
  [ -n "$ROW" ] && [ "$ROW" != "null" ] && break
  sleep 3
done

echo "==> Recent Lambda logs"
aws logs tail "/aws/lambda/$FN" --since 3m --format short 2>/dev/null | tail -n 25 || true

if [ -z "$ROW" ] || [ "$ROW" = "null" ]; then
  echo "FAIL - no DynamoDB row after ${TIMEOUT}s. Check the logs above."
  exit 1
fi

echo "==> DynamoDB row"
echo "$ROW" | python3 -c 'import json,sys;r=json.load(sys.stdin);print(json.dumps({k:list(v.values())[0] for k,v in r.items()},indent=2))'

echo "==> Result JSON"
if aws s3api head-object --bucket "$OUTPUT_BUCKET" --key "results/$ETAG.json" >/dev/null 2>&1; then
  aws s3 cp "s3://$OUTPUT_BUCKET/results/$ETAG.json" - 2>/dev/null | python3 -m json.tool
else
  echo "    (results/$ETAG.json not written - row status may be 'skipped' or 'partial_error')"
fi

echo
echo "PASS - pipeline processed the image. If no email arrived, the SNS subscription"
echo "       is almost certainly unconfirmed (see the warning above) or the mail is in spam."
