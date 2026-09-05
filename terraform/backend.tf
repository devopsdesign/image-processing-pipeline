# Remote state. Configure with:  terraform init -backend-config=backend.hcl
#
# One-time bootstrap (creates the state bucket; safe to run once per account):
#   aws s3api create-bucket --bucket cloudsight-tfstate-<ACCOUNT_ID> --region us-east-1
#   aws s3api put-bucket-versioning --bucket cloudsight-tfstate-<ACCOUNT_ID> \
#     --versioning-configuration Status=Enabled
#
# For a throwaway local test you can delete this file and run `terraform init`
# with local state instead.
terraform {
  backend "s3" {}
}
