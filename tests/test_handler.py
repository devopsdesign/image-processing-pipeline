import importlib
import json

import boto3
import pytest
from moto import mock_aws

REGION = "us-east-1"


@pytest.fixture
def index(monkeypatch):
    monkeypatch.setenv("AWS_XRAY_SDK_ENABLED", "false")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("OUTPUT_BUCKET", "out-bucket")
    monkeypatch.setenv("DYNAMODB_TABLE", "results")
    monkeypatch.setenv("SNS_TOPIC_ARN", f"arn:aws:sns:{REGION}:123456789012:cloudsight")
    monkeypatch.setenv("USE_REKOGNITION", "false")

    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket="in-bucket")
        s3.create_bucket(Bucket="out-bucket")

        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName="results",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "image_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "image_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
        )
        boto3.client("sns", region_name=REGION).create_topic(Name="cloudsight")

        import index as _index

        importlib.reload(_index)
        yield _index


def _event(key="uploads/photo.jpg", etag="deadbeef"):
    return {"Records": [{"s3": {"bucket": {"name": "in-bucket"}, "object": {"key": key, "eTag": etag}}}]}


def test_metadata_only_processing_writes_ddb_and_s3(index):
    result = index.handler(_event(), None)["processed"][0]

    assert result["status"] == "processed"
    assert result["image_id"] == "deadbeef"

    obj = boto3.client("s3", region_name=REGION).get_object(Bucket="out-bucket", Key="results/deadbeef.json")
    payload = json.loads(obj["Body"].read())
    assert payload["analysis_mode"] == "metadata-only"
    assert payload["image_key"] == "uploads/photo.jpg"


def test_duplicate_etag_is_skipped(index):
    index.handler(_event(), None)
    result = index.handler(_event(), None)["processed"][0]

    assert result["status"] == "skipped"
    assert result["reason"] == "duplicate"


def test_unsupported_type_is_skipped(index):
    result = index.handler(_event(key="uploads/notes.txt"), None)["processed"][0]

    assert result["status"] == "skipped"
    assert result["reason"] == "unsupported_type"


def test_missing_etag_falls_back_to_head_object(index):
    boto3.client("s3", region_name=REGION).put_object(Bucket="in-bucket", Key="uploads/x.png", Body=b"data")
    event = {"Records": [{"s3": {"bucket": {"name": "in-bucket"}, "object": {"key": "uploads/x.png"}}}]}

    result = index.handler(event, None)["processed"][0]

    assert result["status"] == "processed"
    assert result["image_id"]
