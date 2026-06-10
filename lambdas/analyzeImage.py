import base64
import json

import boto3

rekognition = boto3.client("rekognition")

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # Rekognition's limit for image bytes

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

        image_b64 = body.get("image")
        if not image_b64:
            return respond(400, {"error": "'image' (base64-encoded JPEG/PNG) is required"})

        try:
            image_bytes = base64.b64decode(image_b64, validate=True)
        except Exception:
            return respond(400, {"error": "'image' is not valid base64"})

        if len(image_bytes) > MAX_IMAGE_BYTES:
            return respond(400, {"error": "Image too large — max 5 MB"})

        try:
            result = rekognition.detect_labels(
                Image={"Bytes": image_bytes},
                MaxLabels=10,
                MinConfidence=70,
            )
        except (
            rekognition.exceptions.InvalidImageFormatException,
            rekognition.exceptions.ImageTooLargeException,
        ) as e:
            return respond(400, {"error": str(e)})

        labels = [
            {"name": l["Name"], "confidence": round(l["Confidence"], 1)}
            for l in result["Labels"]
        ]
        suggested = ", ".join(l["name"] for l in labels[:3])

        return respond(200, {"labels": labels, "suggestedDescription": suggested})
    except json.JSONDecodeError:
        return respond(400, {"error": "Request body must be valid JSON"})
    except Exception as e:
        return respond(500, {"error": str(e)})
