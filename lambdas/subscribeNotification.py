import json
import os

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


def resolve_topic_arn():
    arn = os.environ.get("ORDER_DELETED_TOPIC_ARN")
    if arn:
        return arn
    next_token = None
    while True:
        kwargs = {"NextToken": next_token} if next_token else {}
        resp = sns.list_topics(**kwargs)
        for topic in resp.get("Topics", []):
            topic_arn = topic.get("TopicArn", "")
            if topic_arn.endswith(":order-deleted"):
                return topic_arn
        next_token = resp.get("NextToken")
        if not next_token:
            break
    return None


def lambda_handler(event, context):
    try:
        body = event.get("body") or "{}"
        if isinstance(body, str):
            body = json.loads(body)

        email = body.get("email")
        if not email:
            return respond(400, {"error": "'email' is required"})

        topic_arn = resolve_topic_arn()
        if not topic_arn:
            return respond(500, {"error": "Topic 'order-deleted' not found"})

        resp = sns.subscribe(
            TopicArn=topic_arn,
            Protocol="email",
            Endpoint=email,
            ReturnSubscriptionArn=True,
        )
        subscription_arn = resp.get("SubscriptionArn")
        return respond(
            201,
            {
                "message": "Subscription requested; check your email to confirm",
                "subscriptionArn": subscription_arn,
            },
        )
    except json.JSONDecodeError:
        return respond(400, {"error": "Request body must be valid JSON"})
    except Exception as e:
        return respond(500, {"error": str(e)})
