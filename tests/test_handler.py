import importlib
import json
from urllib.parse import quote

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


def _load(monkeypatch, with_ses, use_rekognition=False):
    monkeypatch.setenv("AWS_XRAY_SDK_ENABLED", "false")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("OUTPUT_BUCKET", "out-bucket")
    monkeypatch.setenv("DYNAMODB_TABLE", "results")
    monkeypatch.setenv("SNS_TOPIC_ARN", f"arn:aws:sns:{REGION}:123456789012:cloudsight")
    monkeypatch.setenv("USE_REKOGNITION", "true" if use_rekognition else "false")
    monkeypatch.setenv("MEDICAL_CONFIDENCE_THRESHOLD", "85")
    if with_ses:
        monkeypatch.setenv("SES_FROM", SES_ADDR)
        monkeypatch.setenv("DOCTOR_EMAIL", SES_ADDR)
    else:
        monkeypatch.delenv("SES_FROM", raising=False)
        monkeypatch.delenv("DOCTOR_EMAIL", raising=False)
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


@pytest.fixture
def index_medical(monkeypatch):
    """Rekognition enabled, with detect_labels/detect_moderation_labels faked to
    return a clear 'Person' result - moto's Rekognition mock can't do real
    image analysis, so the medical branch has to be forced this way to test it.
    """
    with mock_aws():
        _provision(with_ses=True)
        idx = _load(monkeypatch, with_ses=True, use_rekognition=True)
        monkeypatch.setattr(
            idx.rekognition,
            "detect_labels",
            lambda **_: {"Labels": [{"Name": "Person", "Confidence": 99.0}]},
        )
        monkeypatch.setattr(idx.rekognition, "detect_text", lambda **_: {"TextDetections": []})
        monkeypatch.setattr(idx.rekognition, "detect_faces", lambda **_: {"FaceDetails": []})
        monkeypatch.setattr(idx.rekognition, "detect_moderation_labels", lambda **_: {"ModerationLabels": []})
        yield idx


def _event(key="uploads/photo.jpg", etag="deadbeef"):
    return {"Records": [{"s3": {"bucket": {"name": "in-bucket"}, "object": {"key": key, "eTag": etag}}}]}


def test_metadata_only_processing_writes_ddb_and_s3(index):
    result = index.handler(_event(), None)["processed"][0]

    assert result["status"] == "processed"
    assert result["image_id"] == "deadbeef"
    assert result["classification"] == "unclassified"

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


def test_non_medical_classification_sends_no_email(index_ses):
    """USE_REKOGNITION=false -> classification=unclassified -> in-app only,
    even though SES is fully configured and would otherwise be able to send."""
    boto3.client("s3", region_name=REGION).put_object(
        Bucket="in-bucket", Key="uploads/pic.jpg", Body=b"\xff\xd8\xff\xd9jpegbytes"
    )
    result = index_ses.handler(_event(key="uploads/pic.jpg", etag="cafef00d"), None)["processed"][0]

    assert result["status"] == "processed"
    assert result["classification"] == "unclassified"

    quota = boto3.client("ses", region_name=REGION).get_send_quota()
    assert quota["SentLast24Hours"] == 0


def test_medical_classification_notifies_doctor(index_medical):
    boto3.client("s3", region_name=REGION).put_object(
        Bucket="in-bucket", Key="uploads/patient.jpg", Body=b"\xff\xd8\xff\xd9jpegbytes"
    )
    result = index_medical.handler(_event(key="uploads/patient.jpg", etag="cafef00d"), None)["processed"][0]

    assert result["status"] == "processed"
    assert result["classification"] == "medical"

    quota = boto3.client("ses", region_name=REGION).get_send_quota()
    assert quota["SentLast24Hours"] >= 1


def test_url_encoded_unicode_key_is_decoded_before_use(index_medical):
    # S3 event notifications percent-encode non-ASCII bytes (and '+' for spaces).
    # A filename with an accented character arrives percent-encoded in the
    # event, but the real object in S3 is stored under the decoded key. Encode
    # from real_key itself (rather than hand-typing the encoded form) so this
    # doesn't depend on whether the source literal happens to be NFC or NFD -
    # both normalize to the same *visible* "ñ" but are different byte strings.
    real_key = "uploads/niños_hojas.jpg"
    encoded_key = quote(real_key)
    boto3.client("s3", region_name=REGION).put_object(
        Bucket="in-bucket", Key=real_key, Body=b"\xff\xd8\xff\xd9jpegbytes"
    )
    event = {
        "Records": [
            {"s3": {"bucket": {"name": "in-bucket"}, "object": {"key": encoded_key, "eTag": "unicode123"}}}
        ]
    }

    result = index_medical.handler(event, None)["processed"][0]

    assert result["status"] == "processed"
    assert result["key"] == real_key  # decoded, not the raw percent-encoded string

    # _send_rich_email only succeeds (and SES only gets a send) if it read the
    # image back from S3 using the correctly decoded key.
    quota = boto3.client("ses", region_name=REGION).get_send_quota()
    assert quota["SentLast24Hours"] >= 1


# --------------------------------------------------------------------------
# _classify - pure function, no AWS calls, tested directly
# --------------------------------------------------------------------------


def _analysis(mode="rekognition", labels=None):
    labels = labels or []
    return {
        "status": "processed",
        "mode": mode,
        "labels": labels,
        "text": [],
        "faces": [],
        "calls": 1 if mode != "metadata-only" else 0,
    }


def test_classify_metadata_only_is_unclassified(index):
    assert index._classify(_analysis(mode="metadata-only"), []) == "unclassified"


def test_classify_person_above_threshold_is_medical(index):
    labels = [{"name": "Person", "confidence": 97.0}, {"name": "Face", "confidence": 92.0}]
    assert index._classify(_analysis(labels=labels), []) == "medical"


def test_classify_person_below_threshold_is_needs_review(index):
    # A person-ish label present, but too low-confidence to act on automatically.
    labels = [{"name": "Person", "confidence": 60.0}]
    assert index._classify(_analysis(labels=labels), []) == "needs_review"


def test_classify_clear_object_is_non_human(index):
    labels = [{"name": "Toy", "confidence": 95.0}, {"name": "Plastic", "confidence": 80.0}]
    assert index._classify(_analysis(labels=labels), []) == "non_human"


def test_classify_no_labels_is_needs_review(index):
    assert index._classify(_analysis(labels=[]), []) == "needs_review"


def test_classify_moderation_flag_forces_needs_review(index):
    labels = [{"name": "Toy", "confidence": 95.0}]
    moderation = [{"name": "Suggestive", "confidence": 70.0}]
    assert index._classify(_analysis(labels=labels), moderation) == "needs_review"
