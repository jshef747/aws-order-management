import json
import os
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("ORDERS_TABLE", "orders"))
sfn_client = boto3.client("stepfunctions")

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

        table.delete_item(Key={"orderId": order_id})

        # Fire-and-forget: hand the deleted item off to the Step Functions
        # state machine (non-blocking) which fans out to SNS + S3 TXT backup.
        # A Step Functions failure must never break the delete response.
        state_machine_arn = os.environ.get("FANOUT_STATE_MACHINE_ARN")
        if state_machine_arn:
            try:
                sfn_client.start_execution(
                    stateMachineArn=state_machine_arn,
                    input=json.dumps(to_plain(item)),
                )
            except Exception as sfn_err:
                print(f"Step Functions start_execution failed: {sfn_err}")

        return respond(200, {"message": "Order deleted", "order": to_plain(item)})
    except Exception as e:
        return respond(500, {"error": str(e)})
