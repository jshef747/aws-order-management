import json

import boto3
from botocore.exceptions import ClientError

sns = boto3.client("sns")

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

        subscription_arn = body.get("subscriptionArn")
        if not subscription_arn:
            return respond(400, {"error": "'subscriptionArn' is required"})

        try:
            sns.unsubscribe(SubscriptionArn=subscription_arn)
        except ClientError as e:
            # A pending (unconfirmed) subscription cannot be unsubscribed via the
            # API — SNS rejects it, and it expires on its own. Unsubscribe is
            # idempotent ("ensure this subscription is not active"), so treat the
            # pending case as a successful no-op rather than a 500.
            message = e.response.get("Error", {}).get("Message", "")
            if "pending confirmation" in message.lower():
                return respond(200, {"message": "Subscription pending confirmation; nothing to unsubscribe"})
            raise
        return respond(200, {"message": "Unsubscribed"})
    except json.JSONDecodeError:
        return respond(400, {"error": "Request body must be valid JSON"})
    except Exception as e:
        return respond(500, {"error": str(e)})
