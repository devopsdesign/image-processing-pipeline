.PHONY: help build test lint deploy plan destroy app fmt

TF := terraform -chdir=terraform

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-10s\033[0m %s\n", $$1, $$2}'

build: ## Build the Lambda deployment package
	bash scripts/build_lambda.sh

lint: ## Ruff lint
	ruff check lambda tests app

test: ## Run unit tests
	AWS_XRAY_SDK_ENABLED=false pytest

fmt: ## terraform fmt
	$(TF) fmt -recursive

plan: build ## terraform plan
	$(TF) init -backend-config=backend.hcl
	$(TF) plan

deploy: build ## terraform apply
	$(TF) init -backend-config=backend.hcl
	$(TF) apply

destroy: ## terraform destroy
	$(TF) destroy

app: ## Run the Streamlit app locally (needs terraform outputs)
	AWS_REGION=$${AWS_REGION:-us-east-1} \
	INPUT_BUCKET=$$($(TF) output -raw input_bucket) \
	OUTPUT_BUCKET=$$($(TF) output -raw output_bucket) \
	DYNAMODB_TABLE=$$($(TF) output -raw dynamodb_table) \
	streamlit run app/app.py
