#!/bin/bash

# Script to upload test image to S3

set -e

echo "Image Processing Pipeline - Test Upload Script"
echo "================================================"

# Get bucket name from Terraform outputs
cd "$(dirname "$0")/.."
cd terraform

INPUT_BUCKET=$(terraform output -raw input_bucket 2>/dev/null) || {
    echo "Error: Could not get input bucket name"
    echo "Make sure Terraform has been deployed: cd terraform && terraform apply"
    exit 1
}

echo "Input Bucket: $INPUT_BUCKET"

# Verify test image exists
if [ ! -f "../test/sample-image.jpg" ]; then
    echo "Error: Test image not found at test/sample-image.jpg"
    exit 1
fi

echo "Uploading test image..."
aws s3 cp ../test/sample-image.jpg s3://image-processing-pipeline-input-920534282171/uploads/test-$(date +%s).jpg

echo "Upload complete!"
echo ""
echo "Processing should complete in 30-60 seconds..."
echo ""
echo "To check results:"
echo "  1. Check your email for SNS notification"
echo "  2. Query DynamoDB: aws dynamodb scan --table-name image-processing-pipeline-results"
echo "  3. List output S3: aws s3 ls s3://\$(terraform output -raw output_bucket)/results/"