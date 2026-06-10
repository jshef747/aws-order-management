import json

import boto3

translate_client = boto3.client("translate")

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

        text = body.get("text")
        target_language = body.get("targetLanguage")
        if not text or not target_language:
            return respond(400, {"error": "Both 'text' and 'targetLanguage' are required"})

        result = translate_client.translate_text(
            Text=str(text),
            SourceLanguageCode="auto",
            TargetLanguageCode=str(target_language),
        )

        return respond(
            200,
            {
                "translatedText": result["TranslatedText"],
                "sourceLanguage": result["SourceLanguageCode"],
                "targetLanguage": result["TargetLanguageCode"],
            },
        )
    except json.JSONDecodeError:
        return respond(400, {"error": "Request body must be valid JSON"})
    except Exception as e:
        return respond(500, {"error": str(e)})
