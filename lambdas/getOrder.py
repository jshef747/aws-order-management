import json
import os
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("ORDERS_TABLE", "orders"))

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "OPTIONS,GET,POST,PUT,DELETE",
}


def to_plain(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_plain(v) for v in obj]
    return obj


def respond(status, body):
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(body)}


def lambda_handler(event, context):
    try:
        path_params = event.get("pathParameters") or {}
        order_id = path_params.get("id")
        if not order_id:
            return respond(400, {"error": "Missing order id in path"})

        resp = table.get_item(Key={"orderId": order_id})
        item = resp.get("Item")
        if not item:
            return respond(404, {"error": f"Order '{order_id}' not found"})

        return respond(200, {"order": to_plain(item)})
    except Exception as e:
        return respond(500, {"error": str(e)})
