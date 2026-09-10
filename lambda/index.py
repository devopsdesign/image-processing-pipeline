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

VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif")

s3 = boto3.client("s3")
rekognition = boto3.client("rekognition")
sns = boto3.client("sns")
table = boto3.resource("dynamodb").Table(DYNAMODB_TABLE)


def handler(event, context):
    return {"processed": [_process_record(r) for r in event.get("Records", [])]}


def _process_record(record):
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]
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
            preview_url = "(unavailable)"

        if analysis["labels"]:
            labels_line = "Labels:   " + ", ".join(
                f"{lab['name']} {lab['confidence']}%" for lab in analysis["labels"]
            )
        elif analysis["mode"].startswith("metadata"):
            labels_line = "Labels:   (none - Rekognition disabled, metadata-only mode)"
        else:
            labels_line = "Labels:   (none detected)"

        _publish(
            subject=f"[CloudSight] processed {key[:60]}",
            message=(
                "CloudSight Intake - image processed\n\n"
                f"Image:    {key}\n"
                f"ETag:     {image_id}\n"
                f"Status:   {analysis['status']} ({analysis['mode']})\n"
                f"Summary:  {summary}\n"
                f"{labels_line}\n"
                f"Result:   s3://{OUTPUT_BUCKET}/{result_key}\n\n"
                f"Image preview (SigV4 link, valid ~1 hour):\n{preview_url}\n"
            ),
        )
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
