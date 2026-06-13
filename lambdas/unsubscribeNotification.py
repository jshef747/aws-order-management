import json

import boto3

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

        sns.unsubscribe(SubscriptionArn=subscription_arn)
        return respond(200, {"message": "Unsubscribed"})
    except json.JSONDecodeError:
        return respond(400, {"error": "Request body must be valid JSON"})
    except Exception as e:
        return respond(500, {"error": str(e)})
