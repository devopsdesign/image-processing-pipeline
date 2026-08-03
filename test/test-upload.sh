#!/bin/bash
# test-upload.sh - Auto-detect bucket from AWS (GitHub Actions Compatible)

set -e

echo "🚀 Image Processing Pipeline - Test Upload"
echo "=========================================="

# Auto-detect the input bucket by listing S3 buckets and filtering
# This works because GitHub Actions deployed the bucket with a known prefix
INPUT_BUCKET=$(aws s3 ls | grep "image-processing-pipeline-input" | awk '{print $3}' | head -n 1)

if [ -z "$INPUT_BUCKET" ]; then
    echo "❌ Error: Could not find input bucket automatically."
    echo "   Please ensure the pipeline was deployed successfully."
    echo "   Run 'aws s3 ls' to check available buckets."
    exit 1
fi

echo "📦 Detected Input Bucket: $INPUT_BUCKET"

# Verify test image exists
TEST_IMAGE="${1:-test/sample-image.jpg}"
if [ ! -f "$TEST_IMAGE" ]; then
    echo "❌ Error: Test image not found at $TEST_IMAGE"
    exit 1
fi

# Generate unique filename
TIMESTAMP=$(date +%s)
S3_KEY="uploads/test-${TIMESTAMP}.jpg"

echo "📤 Uploading $TEST_IMAGE to s3://$INPUT_BUCKET/$S3_KEY..."
aws s3 cp "$TEST_IMAGE" "s3://$INPUT_BUCKET/$S3_KEY"

echo "✅ Upload complete!"
echo ""
echo "🔍 Processing in 30-60 seconds..."
echo ""
echo "📋 Verification:"
echo "   1. Check email for SNS notification"
echo "   2. Check logs: aws logs tail /aws/lambda/image-processing-pipeline-processor --follow"
echo "   3. Check DynamoDB: aws dynamodb scan --table-name image-processing-pipeline-results --query 'Items[*].{ID:image_id, Status:status}'"