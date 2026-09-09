# Remote state in S3 with native lockfile locking (no DynamoDB table needed).
#
# `bucket` and `region` are injected at init time so nothing account-specific is
# committed to the repo. CI does:
#
#   terraform init -reconfigure \
#     -backend-config="bucket=$TF_STATE_BUCKET" \
#     -backend-config="region=$AWS_REGION"
#
# The state bucket itself is created by the "Ensure Terraform state bucket"
# step in .github/workflows/deploy.yml before this runs, so no local terminal
# is required.
#
# For a one-off local run you can instead: terraform init -backend-config=backend.hcl
terraform {
  backend "s3" {
    key          = "cloudsight-intake/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
