"""CloudSight Intake - read-only HTTP API over the results table.

GET /images                      -> recent items (?status=processed&limit=20)
GET /images/{image_id}           -> all rows for one image_id

No auth - this is a demo read endpoint over non-sensitive metadata (labels,
filenames, counts; never the image itself). Throttled at the API Gateway
stage (5 req/s, burst 10) to bound cost/abuse.
"""

import json
import os

import boto3
from boto3.dynamodb.conditions import Key

TABLE = os.environ["DYNAMODB_TABLE"]
table = boto3.resource("dynamodb").Table(TABLE)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def handler(event, _context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path_params = event.get("pathParameters") or {}
    query = event.get("queryStringParameters") or {}

    if method != "GET":
        return _response(405, {"error": "method not allowed"})

    try:
        if "image_id" in path_params:
            return _get_one(path_params["image_id"])
        return _list(query)
    except Exception as exc:  # noqa: BLE001
        return _response(500, {"error": str(exc)})


def _get_one(image_id):
    resp = table.query(KeyConditionExpression=Key("image_id").eq(image_id))
    items = resp.get("Items", [])
    if not items:
        return _response(404, {"error": "not found", "image_id": image_id})
    return _response(200, {"items": [_plain(i) for i in items]})


def _list(query):
    try:
        limit = min(int(query.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
    except ValueError:
        limit = DEFAULT_LIMIT
    status = query.get("status")

    if status:
        resp = table.query(
            IndexName="StatusIndex",
            KeyConditionExpression=Key("status").eq(status),
            ScanIndexForward=False,
            Limit=limit,
        )
        items = resp.get("Items", [])
    else:
        resp = table.scan(Limit=limit)
        items = sorted(resp.get("Items", []), key=lambda i: i.get("timestamp", ""), reverse=True)

    return _response(200, {"count": len(items), "items": [_plain(i) for i in items]})


def _plain(item):
    """DynamoDB Decimals -> plain JSON-serialisable values."""
    return json.loads(json.dumps(item, default=str))


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }
