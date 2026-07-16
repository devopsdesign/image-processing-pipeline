import os
import json
import tempfile
from pathlib import Path
import streamlit as st
import boto3
from PIL import Image

st.set_page_config(page_title="CloudSight Intake Demo", page_icon="☁️", layout="centered")

st.title("CloudSight Intake Demo")
st.markdown("A simple recruiter-friendly demo for the serverless image processing workflow.")

# Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
INPUT_BUCKET = os.getenv("INPUT_BUCKET", "")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "")

if not INPUT_BUCKET or not OUTPUT_BUCKET:
    st.warning("Set INPUT_BUCKET and OUTPUT_BUCKET environment variables to enable upload and result viewing.")

s3 = boto3.client("s3", region_name=AWS_REGION)

uploaded_file = st.file_uploader("Upload an image", type=["jpg", "jpeg", "png", "gif"])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Uploaded image", use_container_width=True)

    if st.button("Process image"):
        if not INPUT_BUCKET or not OUTPUT_BUCKET:
            st.error("Bucket names are not configured.")
            st.stop()

        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            temp_path = tmp.name

        object_key = f"uploads/{uploaded_file.name}"
        s3.upload_file(temp_path, INPUT_BUCKET, object_key)

        os.remove(temp_path)

        st.success(f"Image uploaded to s3://{INPUT_BUCKET}/{object_key}")
        st.info("Processing is triggered through the event-driven workflow. Results will appear shortly.")

        st.subheader("What this demo shows")
        st.write("- S3 receives the uploaded image")
        st.write("- Lambda is triggered by the upload event")
        st.write("- Results are stored for review")

        st.markdown("### Result preview")
        result_key = f"results/{Path(uploaded_file.name).stem}.json"

        try:
            response = s3.get_object(Bucket=OUTPUT_BUCKET, Key=result_key)
            content = response["Body"].read().decode("utf-8")
            result_data = json.loads(content)
            st.json(result_data)
        except Exception as exc:
            st.info(f"Result file not found yet. Reason: {exc}")
