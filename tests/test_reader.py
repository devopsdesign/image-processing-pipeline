import importlib

import boto3
import pytest
from moto import mock_aws

REGION = "us-east-1"


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("DYNAMODB_TABLE", "results")

    with mock_aws():
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
                {"AttributeName": "status", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "StatusIndex",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "timestamp", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        table = boto3.resource("dynamodb", region_name=REGION).Table("results")
        table.put_item(
            Item={
                "image_id": "abc123",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "status": "processed",
                "summary": "5 labels",
            }
        )
        table.put_item(
            Item={
                "image_id": "def456",
                "timestamp": "2026-01-02T00:00:00+00:00",
                "status": "skipped",
                "summary": "duplicate",
            }
        )

        import reader as _reader

        importlib.reload(_reader)
        yield _reader


def _event(method="GET", path_params=None, query=None):
    return {
        "requestContext": {"http": {"method": method}},
        "pathParameters": path_params,
        "queryStringParameters": query,
    }


def test_get_one_found(reader):
    resp = reader.handler(_event(path_params={"image_id": "abc123"}), None)
    assert resp["statusCode"] == 200
    assert "abc123" in resp["body"]


def test_get_one_not_found(reader):
    resp = reader.handler(_event(path_params={"image_id": "nope"}), None)
    assert resp["statusCode"] == 404


def test_list_filters_by_status(reader):
    resp = reader.handler(_event(query={"status": "processed"}), None)
    assert resp["statusCode"] == 200
    assert "abc123" in resp["body"]
    assert "def456" not in resp["body"]


def test_list_default_scans_everything(reader):
    resp = reader.handler(_event(), None)
    assert resp["statusCode"] == 200
    assert "abc123" in resp["body"]
    assert "def456" in resp["body"]


def test_rejects_non_get(reader):
    resp = reader.handler(_event(method="POST"), None)
    assert resp["statusCode"] == 405
