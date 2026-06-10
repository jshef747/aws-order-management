import json
import os
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

        body = event.get("body") or "{}"
        if isinstance(body, str):
            body = json.loads(body)

        price = body.get("price")
        description = body.get("description")
        if price is None and description is None:
            return respond(400, {"error": "Provide at least one of 'price' or 'description'"})

        resp = table.get_item(Key={"orderId": order_id})
        if not resp.get("Item"):
            return respond(404, {"error": f"Order '{order_id}' not found"})

        updates = {"lastModifiedDate": datetime.now(timezone.utc).isoformat()}
        if price is not None:
            try:
                updates["price"] = Decimal(str(price))
            except Exception:
                return respond(400, {"error": "'price' must be a number"})
        if description is not None:
            updates["description"] = str(description)

        # Attribute-name placeholders keep us safe if a field ever becomes a reserved word.
        expr_names = {f"#f{i}": k for i, k in enumerate(updates)}
        expr_values = {f":v{i}": v for i, v in enumerate(updates.values())}
        update_expr = "SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(updates)))

        result = table.update_item(
            Key={"orderId": order_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW",
        )

        return respond(200, {"message": "Order updated", "order": to_plain(result["Attributes"])})
    except json.JSONDecodeError:
        return respond(400, {"error": "Request body must be valid JSON"})
    except Exception as e:
        return respond(500, {"error": str(e)})
