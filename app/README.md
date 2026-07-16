# Demo UI

This folder contains a lightweight Streamlit demo for the CloudSight Intake project.

## Run locally

```bash
cd app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INPUT_BUCKET=<your-input-bucket>
export OUTPUT_BUCKET=<your-output-bucket>
export AWS_REGION=us-east-1
streamlit run app.py
```

## What it does

- Uploads an image to the S3 input bucket
- Triggers the serverless workflow
- Displays a simple result preview when the output JSON is available
