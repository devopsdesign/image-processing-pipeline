"""CloudSight Intake - Streamlit front end.

Flow:
  1. User uploads a JPG/PNG.
  2. App writes it to  s3://<INPUT_BUCKET>/uploads/<name>  using st.secrets creds.
  3. App computes the object's ETag (MD5 of the bytes) - the same value the
     Lambda uses as `image_id`.
  4. App polls DynamoDB (and then the S3 output bucket) by that ETag until the
     Lambda has written a result, then shows a live success indicator, the
     processing duration, and the summary JSON.

Configuration is read from st.secrets on Streamlit Community Cloud, or from
environment variables when run locally:

    AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    INPUT_BUCKET, OUTPUT_BUCKET, DYNAMODB_TABLE
"""

import hashlib
import json
import os
import time

import boto3
import streamlit as st
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError

st.set_page_config(page_title="CloudSight Intake", page_icon="🛰️", layout="centered")

ALLOWED_TYPES = ["jpg", "jpeg", "png"]
POLL_TIMEOUT_SECONDS = 90
POLL_INTERVAL_SECONDS = 3


def cfg(name, default=""):
    """Env var wins locally; fall back to st.secrets on Streamlit Cloud."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        return str(st.secrets[name])
    except Exception:
        return default


REGION = cfg("AWS_REGION", "us-east-1")
INPUT_BUCKET = cfg("INPUT_BUCKET")
OUTPUT_BUCKET = cfg("OUTPUT_BUCKET")
DDB_TABLE = cfg("DYNAMODB_TABLE")


@st.cache_resource
def aws_clients():
    kwargs = {"region_name": REGION}
    access_key, secret_key = cfg("AWS_ACCESS_KEY_ID"), cfg("AWS_SECRET_ACCESS_KEY")
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
    session = boto3.session.Session(**kwargs)
    return session.client("s3"), session.resource("dynamodb")


def find_result(table, etag):
    resp = table.query(KeyConditionExpression=Key("image_id").eq(etag), Limit=1)
    items = resp.get("Items") or []
    return items[0] if items else None


def plain(obj):
    """DynamoDB returns Decimals - make the item JSON-serialisable."""
    return json.loads(json.dumps(obj, default=str))


# --------------------------------------------------------------------------- UI

st.title("🛰️ CloudSight Intake")
st.caption("Upload an image → S3 event → Lambda + Rekognition → DynamoDB + S3 results")

missing = [
    name
    for name, value in {
        "INPUT_BUCKET": INPUT_BUCKET,
        "OUTPUT_BUCKET": OUTPUT_BUCKET,
        "DYNAMODB_TABLE": DDB_TABLE,
    }.items()
    if not value
]
if missing:
    st.error("Missing configuration: " + ", ".join(missing))
    st.caption("Set these in the Streamlit **Secrets** panel (or as environment variables locally).")
    st.stop()

s3, dynamodb = aws_clients()
table = dynamodb.Table(DDB_TABLE)

uploaded = st.file_uploader("Choose a JPG or PNG image", type=ALLOWED_TYPES)
if uploaded is None:
    st.stop()

data = uploaded.getvalue()
etag = hashlib.md5(data).hexdigest()  # == S3 single-part upload ETag == Lambda image_id

st.image(data, caption=uploaded.name, use_container_width=True)
st.code(f"image_id (ETag): {etag}", language="text")

if not st.button("Process image", type="primary"):
    st.stop()

object_key = f"uploads/{uploaded.name}"
started = time.monotonic()
record = None

with st.status("Uploading to S3…", expanded=True) as status:
    try:
        s3.put_object(
            Bucket=INPUT_BUCKET,
            Key=object_key,
            Body=data,
            ContentType=uploaded.type or "application/octet-stream",
        )
    except (ClientError, BotoCoreError) as exc:
        status.update(label="Upload failed", state="error")
        st.exception(exc)
        st.stop()

    st.write(f"Uploaded `s3://{INPUT_BUCKET}/{object_key}`")
    status.update(label="Waiting for the pipeline…")

    deadline = started + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            record = find_result(table, etag)
        except (ClientError, BotoCoreError) as exc:
            status.update(label="DynamoDB query failed", state="error")
            st.exception(exc)
            st.stop()
        if record:
            break
        st.write(f"polling… {int(time.monotonic() - started)}s")
        time.sleep(POLL_INTERVAL_SECONDS)

    if record is None:
        status.update(label=f"Timed out after {POLL_TIMEOUT_SECONDS}s", state="error")
        st.warning(
            "No result yet. Check the Lambda logs: "
            "`aws logs tail /aws/lambda/cloudsight-intake-processor --follow`"
        )
        st.stop()

    elapsed = time.monotonic() - started
    status.update(label=f"Done in {elapsed:.1f}s", state="complete")

# ----------------------------------------------------------------------- result

st.success(f"✅ Image processed — status `{record.get('status', 'unknown')}`")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Processing time", f"{elapsed:.1f} s")
c2.metric("Labels", int(record.get("label_count", 0)))
c3.metric("Text items", int(record.get("text_count", 0)))
c4.metric("Faces", int(record.get("face_count", 0)))

st.write(
    f"**Analysis mode:** `{record.get('analysis_mode', '—')}`  ·  "
    f"**Rekognition calls:** {int(record.get('rekognition_calls', 0))}  ·  "
    f"**Summary:** {record.get('summary', '—')}"
)

st.subheader("Summary JSON")
try:
    obj = s3.get_object(Bucket=OUTPUT_BUCKET, Key=f"results/{etag}.json")
    st.json(json.loads(obj["Body"].read()))
except (ClientError, BotoCoreError):
    st.info("Full JSON not in the output bucket yet — showing the DynamoDB record.")
    st.json(plain(record))
