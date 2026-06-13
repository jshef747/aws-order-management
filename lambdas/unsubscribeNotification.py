import json
import os

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


def find_subscription_arns(topic_arn, email):
    """All subscription ARNs on the topic whose endpoint matches the email."""
    arns = []
    next_token = None
    while True:
        kwargs = {"TopicArn": topic_arn}
        if next_token:
            kwargs["NextToken"] = next_token
        resp = sns.list_subscriptions_by_topic(**kwargs)
        for sub in resp.get("Subscriptions", []):
            if sub.get("Endpoint", "").lower() == email.lower():
                arns.append(sub.get("SubscriptionArn", ""))
        next_token = resp.get("NextToken")
        if not next_token:
            break
    return arns


def lambda_handler(event, context):
    try:
        body = event.get("body") or "{}"
        if isinstance(body, str):
            body = json.loads(body)

        email = (body.get("email") or "").strip()
        if not email:
            return respond(400, {"error": "'email' is required"})

        topic_arn = resolve_topic_arn()
        if not topic_arn:
            return respond(500, {"error": "Topic 'order-deleted' not found"})

        arns = find_subscription_arns(topic_arn, email)
        if not arns:
            # Idempotent: "ensure this email is not subscribed" — already true.
            return respond(200, {"message": f"No active subscription for {email}"})

        unsubscribed = 0
        pending = 0
        for arn in arns:
            # A pending (unconfirmed) subscription has the literal ARN
            # "PendingConfirmation" and cannot be unsubscribed via the API;
            # it expires on its own, so treat it as a no-op.
            if arn == "PendingConfirmation":
                pending += 1
                continue
            try:
                sns.unsubscribe(SubscriptionArn=arn)
                unsubscribed += 1
            except ClientError as e:
                message = e.response.get("Error", {}).get("Message", "")
                if "pending confirmation" in message.lower():
                    pending += 1
                else:
                    raise

        if unsubscribed:
            return respond(200, {"message": f"Unsubscribed {email}"})
        return respond(200, {"message": f"Subscription for {email} is pending confirmation; nothing to unsubscribe"})
    except json.JSONDecodeError:
        return respond(400, {"error": "Request body must be valid JSON"})
    except Exception as e:
        return respond(500, {"error": str(e)})
