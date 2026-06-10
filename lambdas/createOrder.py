import json
import os
import uuid
from datetime import datetime, timezone
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


def respond(status, body):
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(body)}


def lambda_handler(event, context):
    try:
        body = event.get("body") or "{}"
        if isinstance(body, str):
            body = json.loads(body)

        price = body.get("price")
        description = body.get("description")
        if price is None or description is None:
            return respond(400, {"error": "Both 'price' and 'description' are required"})
        try:
            price = Decimal(str(price))
        except Exception:
            return respond(400, {"error": "'price' must be a number"})

        now = datetime.now(timezone.utc).isoformat()
        item = {
            "orderId": str(uuid.uuid4()),
            "gsiPk": "ORDER",
            "creationDate": now,
            "lastModifiedDate": now,
            "price": price,
            "description": str(description),
        }
        table.put_item(Item=item)

        item["price"] = float(item["price"])
        return respond(201, {"message": "Order created", "order": item})
    except json.JSONDecodeError:
        return respond(400, {"error": "Request body must be valid JSON"})
    except Exception as e:
        return respond(500, {"error": str(e)})
