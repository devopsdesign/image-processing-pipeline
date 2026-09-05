# CloudSight Intake - Streamlit demo

Front end for the serverless pipeline. Full docs: [`../README.md`](../README.md).

## Run locally

```bash
cd app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export AWS_REGION=us-east-1
export INPUT_BUCKET=$(cd ../terraform && terraform output -raw input_bucket)
export OUTPUT_BUCKET=$(cd ../terraform && terraform output -raw output_bucket)
export DYNAMODB_TABLE=$(cd ../terraform && terraform output -raw dynamodb_table)
# AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from your environment or ~/.aws

streamlit run app.py
```

## Streamlit Community Cloud

Main file path: `app/app.py`. Put credentials and bucket names in the app's
**Secrets** (see `../.streamlit/secrets.toml.example`). Step-by-step in the root README.
