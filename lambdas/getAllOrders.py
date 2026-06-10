import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

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


def lambda_handler(event, context):
    try:
        orders = []
        kwargs = {
            "IndexName": "gsi-by-date",
            "KeyConditionExpression": Key("gsiPk").eq("ORDER"),
            "ScanIndexForward": True,  # oldest first by creationDate
        }
        while True:
            resp = table.query(**kwargs)
            orders.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key

        return {
            "statusCode": 200,
            "headers": HEADERS,
            "body": json.dumps({"count": len(orders), "orders": to_plain(orders)}),
        }
    except Exception as e:
        return {"statusCode": 500, "headers": HEADERS, "body": json.dumps({"error": str(e)})}
