"""CloudSight Intake - image processing Lambda.

S3 ObjectCreated (uploads/*.jpg|jpeg|png|gif)
  -> ETag-based idempotency check against DynamoDB
  -> optional cascading Amazon Rekognition (labels -> text -> faces)
  -> summary row in DynamoDB + full JSON in the output bucket
  -> SNS success / failure notification

Failures are re-raised so the async invocation lands in the SQS DLQ.
"""

import json
import logging
import os
from datetime import UTC, datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import unquote_plus

import boto3
from aws_xray_sdk.core import patch_all
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

# Honours AWS_XRAY_SDK_ENABLED=false (set in tests / local runs).
patch_all()

logger = logging.getLogger()
logger.setLevel(logging.INFO)

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
USE_REKOGNITION = os.environ.get("USE_REKOGNITION", "false").lower() == "true"
SES_FROM = os.environ.get("SES_FROM")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL") or SES_FROM

VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif")
MAX_INLINE_BYTES = 6_000_000  # keep the SES raw message under the 10 MB limit

s3 = boto3.client("s3")
rekognition = boto3.client("rekognition")
sns = boto3.client("sns")
ses = boto3.client("ses")
table = boto3.resource("dynamodb").Table(DYNAMODB_TABLE)


def handler(event, context):
    return {"processed": [_process_record(r) for r in event.get("Records", [])]}


def _process_record(record):
    bucket = record["s3"]["bucket"]["name"]
    # S3 event notification keys are URL-encoded (percent-encoding for non-ASCII
    # bytes, '+' for spaces) - decode once so every downstream S3/Rekognition
    # call uses the real key. Without this, any filename with accented/unicode
    # characters (e.g. macOS NFD-normalized names) fails with
    # InvalidS3ObjectException / NoSuchKey while looking fine in the console.
    key = unquote_plus(record["s3"]["object"]["key"])
    image_id = record["s3"]["object"].get("eTag", "").strip('"')

    try:
        if not key.lower().endswith(VALID_EXTENSIONS):
            logger.warning("Unsupported file type: %s", key)
            return {"key": key, "status": "skipped", "reason": "unsupported_type"}

        if not image_id:
            image_id = s3.head_object(Bucket=bucket, Key=key)["ETag"].strip('"')

        if _already_processed(image_id):
            logger.info("Duplicate ETag %s (%s) - skipping", image_id, key)
            return {"key": key, "image_id": image_id, "status": "skipped", "reason": "duplicate"}

        analysis = _analyze(bucket, key) if USE_REKOGNITION else _metadata_only()
        summary = _summarize(analysis)
        now = datetime.now(UTC).isoformat()

        item = {
            "image_id": image_id,
            "timestamp": now,
            "image_key": key,
            "status": analysis["status"],
            "analysis_mode": analysis["mode"],
            "label_count": len(analysis["labels"]),
            "text_count": len(analysis["text"]),
            "face_count": len(analysis["faces"]),
            "rekognition_calls": analysis["calls"],
            "summary": summary,
        }
        table.put_item(Item=item)

        result_key = f"results/{image_id}.json"
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=result_key,
            Body=json.dumps({**item, **analysis}, default=str),
            ContentType="application/json",
        )

        try:
            preview_url = s3.generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600
            )
        except ClientError:
            preview_url = ""

        subject = f"[CloudSight] processed {key.rsplit('/', 1)[-1]}"[:100]
        plain_body = (
            "CloudSight Intake - image processed\n\n"
            f"Image:    {key}\n"
            f"ETag:     {image_id}\n"
            f"Status:   {analysis['status']} ({analysis['mode']})\n"
            f"Summary:  {summary}\n"
            f"{_labels_line(analysis)}\n"
            f"Result:   s3://{OUTPUT_BUCKET}/{result_key}\n"
            + (f"\nFull-size image (SigV4 link, ~1h):\n{preview_url}\n" if preview_url else "")
        )

        # Rich HTML email with the image embedded inline; SNS plain-text is the fallback.
        if not _send_rich_email(subject, plain_body, bucket, key, image_id, analysis, summary, result_key):
            _publish(subject=subject, message=plain_body)

        return {"key": key, "image_id": image_id, "status": "processed", "summary": summary}

    except Exception as exc:  # noqa: BLE001 - notify, then let the DLQ catch it
        logger.exception("Processing failed for %s", key)
        _publish(
            subject=f"[CloudSight] FAILED {key[:60]}",
            message=f"Processing failed for s3://{bucket}/{key}\n\n{str(exc)[:1500]}",
            best_effort=True,
        )
        raise


def _already_processed(image_id):
    try:
        resp = table.query(KeyConditionExpression=Key("image_id").eq(image_id), Limit=1)
        return resp.get("Count", 0) > 0
    except ClientError:
        logger.warning("Idempotency check failed for %s - processing anyway", image_id, exc_info=True)
        return False


def _metadata_only():
    return {"status": "processed", "mode": "metadata-only", "labels": [], "text": [], "faces": [], "calls": 0}


def _analyze(bucket, key):
    out = {"status": "processed", "mode": "rekognition", "labels": [], "text": [], "faces": [], "calls": 0}
    image = {"S3Object": {"Bucket": bucket, "Name": key}}

    try:
        resp = rekognition.detect_labels(Image=image, MaxLabels=5, MinConfidence=75)
        out["labels"] = [{"name": lbl["Name"], "confidence": round(lbl["Confidence"], 2)} for lbl in resp["Labels"]]
        out["calls"] += 1
    except ClientError:
        logger.warning("detect_labels failed", exc_info=True)

    if out["labels"]:
        try:
            resp = rekognition.detect_text(Image=image)
            out["text"] = [
                {"value": d["DetectedText"], "confidence": round(d["Confidence"], 2)}
                for d in resp["TextDetections"]
                if d["Type"] == "LINE"
            ]
            out["calls"] += 1
        except ClientError:
            logger.warning("detect_text failed", exc_info=True)

    if out["labels"] or out["text"]:
        try:
            resp = rekognition.detect_faces(Image=image, Attributes=["DEFAULT"])
            out["faces"] = [{"confidence": round(f["Confidence"], 2)} for f in resp["FaceDetails"][:3]]
            out["calls"] += 1
        except ClientError:
            logger.warning("detect_faces failed", exc_info=True)

    if out["calls"] == 0:
        out["status"] = "partial_error"
        out["mode"] = "rekognition-fallback"
    return out


def _summarize(analysis):
    parts = []
    if analysis["labels"]:
        parts.append(f"{len(analysis['labels'])} labels")
    if analysis["text"]:
        parts.append(f"{len(analysis['text'])} text items")
    if analysis["faces"]:
        parts.append(f"{len(analysis['faces'])} faces")
    return ", ".join(parts) if parts else "no analysis data"


def _publish(subject, message, best_effort=False):
    try:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=message)
    except ClientError:
        if not best_effort:
            raise
        logger.error("SNS publish failed", exc_info=True)


def _labels_line(analysis):
    if analysis["labels"]:
        return "Labels:   " + ", ".join(f"{x['name']} {x['confidence']}%" for x in analysis["labels"])
    if analysis["mode"].startswith("metadata"):
        return "Labels:   (none - Rekognition disabled, metadata-only mode)"
    return "Labels:   (none detected)"


def _send_rich_email(subject, plain_body, bucket, key, image_id, analysis, summary, result_key):
    """HTML email with the uploaded image embedded inline (CID). True if SES sent it."""
    if not SES_FROM:
        return False
    try:
        img_bytes = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError:
        logger.warning("Could not read image for rich email", exc_info=True)
        return False

    inline = len(img_bytes) <= MAX_INLINE_BYTES
    subtype = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif"}.get(
        key.rsplit(".", 1)[-1].lower(), "jpeg"
    )
    rows = "".join(
        f"<tr><td style='padding:2px 14px 2px 0'>{x['name']}</td>"
        f"<td style='padding:2px 0;color:#6b7280'>{x['confidence']}%</td></tr>"
        for x in analysis["labels"]
    ) or "<tr><td style='color:#6b7280'>none</td></tr>"
    img_html = (
        "<img src='cid:preview' alt='uploaded image' "
        "style='max-width:480px;border-radius:8px;border:1px solid #e5e7eb'>"
        if inline
        else "<p style='color:#6b7280'>(image too large to embed inline)</p>"
    )
    html = (
        "<html><body style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#111827\">"
        "<h2 style='margin:0 0 2px'>CloudSight Intake &mdash; image processed</h2>"
        f"<p style='margin:0 0 12px;color:#6b7280'>{key}</p>"
        f"{img_html}"
        "<table style='margin:14px 0;border-collapse:collapse;font-size:14px'>"
        "<tr><td style='padding:2px 14px 2px 0'><b>Status</b></td>"
        f"<td>{analysis['status']} ({analysis['mode']})</td></tr>"
        f"<tr><td style='padding:2px 14px 2px 0'><b>Summary</b></td><td>{summary}</td></tr>"
        f"<tr><td style='padding:2px 14px 2px 0'><b>ETag</b></td><td>{image_id}</td></tr>"
        "</table>"
        "<h3 style='margin:8px 0 4px'>Labels</h3>"
        f"<table style='border-collapse:collapse;font-size:14px'>{rows}</table>"
        f"<p style='margin:14px 0 0;font-size:12px;color:#9ca3af'>Result JSON: "
        f"s3://{OUTPUT_BUCKET}/{result_key}</p>"
        "</body></html>"
    )

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = SES_FROM
    msg["To"] = NOTIFY_EMAIL
    alt = MIMEMultipart("alternative")
    msg.attach(alt)
    alt.attach(MIMEText(plain_body, "plain"))
    alt.attach(MIMEText(html, "html"))
    if inline:
        part = MIMEImage(img_bytes, _subtype=subtype)
        part.add_header("Content-ID", "<preview>")
        part.add_header("Content-Disposition", "inline", filename=key.rsplit("/", 1)[-1])
        msg.attach(part)

    try:
        ses.send_raw_email(
            Source=SES_FROM, Destinations=[NOTIFY_EMAIL], RawMessage={"Data": msg.as_string()}
        )
        logger.info("Rich email sent via SES to %s", NOTIFY_EMAIL)
        return True
    except ClientError:
        logger.warning("SES send failed - falling back to SNS", exc_info=True)
        return False
