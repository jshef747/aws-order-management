import os

import boto3

s3 = boto3.client("s3")

BACKUP_BUCKET = os.environ.get("BACKUP_BUCKET", "order-backups")


def lambda_handler(event, context):
    # Invoked by Step Functions: 'event' IS the deleted order dict itself
    # (the JSON input from start_execution), NOT an API-Gateway-proxy event.
    try:
        order = event or {}
        order_id = order.get("orderId")

        lines = [f"{key}: {value}" for key, value in order.items()]
        text = "\n".join(lines)

        key = f"order-{order_id}.txt"
        s3.put_object(
            Bucket=BACKUP_BUCKET,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType="text/plain",
        )

        return {"backedUp": True, "key": key, "orderId": order_id}
    except Exception as e:
        return {"backedUp": False, "error": str(e), "orderId": event.get("orderId") if isinstance(event, dict) else None}
