#!/bin/bash
# test-upload.sh - Upload test images to S3

set -e

echo "🚀 Image Processing Pipeline - Test Upload"
echo "=========================================="

# Get bucket name
cd "$(dirname "$0")/.."
cd terraform
INPUT_BUCKET=$(terraform output -raw input_bucket 2>/dev/null) || {
    echo "❌ Error: Could not get input bucket. Run 'terraform apply' first."
    exit 1
}
cd ..

# Default test image
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
echo "🔍 Expected processing time: 30-60 seconds"
echo ""
echo "📋 Verification commands:"
echo "  1. Check email for SNS notification"
echo "  2. Query results: aws dynamodb scan --table-name image-processing-pipeline-results"
echo "  3. List outputs: aws s3 ls s3://$(terraform output -raw output_bucket)/results/"
echo "  4. View logs: aws logs tail /aws/lambda/image-processing-pipeline-processor --follow"