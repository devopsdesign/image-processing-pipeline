import importlib
import json

import boto3
import pytest
from moto import mock_aws

REGION = "us-east-1"
SES_ADDR = "notify@example.com"


def _provision(with_ses):
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
    if with_ses:
        boto3.client("ses", region_name=REGION).verify_email_identity(EmailAddress=SES_ADDR)


def _load(monkeypatch, with_ses):
    monkeypatch.setenv("AWS_XRAY_SDK_ENABLED", "false")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("OUTPUT_BUCKET", "out-bucket")
    monkeypatch.setenv("DYNAMODB_TABLE", "results")
    monkeypatch.setenv("SNS_TOPIC_ARN", f"arn:aws:sns:{REGION}:123456789012:cloudsight")
    monkeypatch.setenv("USE_REKOGNITION", "false")
    if with_ses:
        monkeypatch.setenv("SES_FROM", SES_ADDR)
    else:
        monkeypatch.delenv("SES_FROM", raising=False)
    import index as _index

    importlib.reload(_index)
    return _index


@pytest.fixture
def index(monkeypatch):
    with mock_aws():
        _provision(with_ses=False)
        yield _load(monkeypatch, with_ses=False)


@pytest.fixture
def index_ses(monkeypatch):
    with mock_aws():
        _provision(with_ses=True)
        yield _load(monkeypatch, with_ses=True)


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


def test_rich_email_sent_via_ses_when_configured(index_ses):
    boto3.client("s3", region_name=REGION).put_object(
        Bucket="in-bucket", Key="uploads/pic.jpg", Body=b"\xff\xd8\xff\xd9jpegbytes"
    )
    event = _event(key="uploads/pic.jpg", etag="cafef00d")

    result = index_ses.handler(event, None)["processed"][0]
    assert result["status"] == "processed"

    quota = boto3.client("ses", region_name=REGION).get_send_quota()
    assert quota["SentLast24Hours"] >= 1


def test_url_encoded_unicode_key_is_decoded_before_use(index_ses):
    # S3 event notifications percent-encode non-ASCII bytes (and '+' for spaces).
    # A macOS NFD filename like "niños_hojas.jpg" arrives as
    # "uploads/nin%CC%83os_hojas.jpg" in the event, but the real object in S3
    # is stored under the decoded key.
    real_key = "uploads/niños_hojas.jpg"  # n + combining tilde (NFD)
    encoded_key = "uploads/nin%CC%83os_hojas.jpg"
    boto3.client("s3", region_name=REGION).put_object(
        Bucket="in-bucket", Key=real_key, Body=b"\xff\xd8\xff\xd9jpegbytes"
    )
    event = {
        "Records": [
            {"s3": {"bucket": {"name": "in-bucket"}, "object": {"key": encoded_key, "eTag": "unicode123"}}}
        ]
    }

    result = index_ses.handler(event, None)["processed"][0]

    assert result["status"] == "processed"
    assert result["key"] == real_key  # decoded, not the raw percent-encoded string

    # _send_rich_email only succeeds (and SES only gets a send) if it read the
    # image back from S3 using the correctly decoded key.
    quota = boto3.client("ses", region_name=REGION).get_send_quota()
    assert quota["SentLast24Hours"] >= 1
