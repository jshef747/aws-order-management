import io
import json
import os

import boto3
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

s3 = boto3.client("s3")
BUCKET = os.environ.get("BACKUP_BUCKET", "order-backups")

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "OPTIONS,GET,POST,PUT,DELETE",
}

SUMMARY_KEY = "deleted-orders-summary.pdf"


def respond(status, body):
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(body)}


def _list_txt_keys():
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".txt"):
                keys.append(key)
    keys.sort()
    return keys


def _build_pdf(sections):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER)
    styles = getSampleStyleSheet()
    story = [Paragraph("Deleted Orders Summary", styles["Title"]), Spacer(1, 12)]

    if not sections:
        story.append(Paragraph("No deleted orders", styles["Normal"]))
    else:
        for key, text in sections:
            story.append(Paragraph(key, styles["Heading2"]))
            for line in text.splitlines() or [""]:
                # escape characters that reportlab's mini-HTML would choke on
                safe = (
                    line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                story.append(Paragraph(safe or "&nbsp;", styles["Normal"]))
            story.append(Spacer(1, 12))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def lambda_handler(event, context):
    try:
        sections = []
        for key in _list_txt_keys():
            obj = s3.get_object(Bucket=BUCKET, Key=key)
            text = obj["Body"].read().decode("utf-8", errors="replace")
            sections.append((key, text))

        pdf_bytes = _build_pdf(sections)

        s3.put_object(
            Bucket=BUCKET,
            Key=SUMMARY_KEY,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )

        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET, "Key": SUMMARY_KEY},
            ExpiresIn=3600,
        )

        return respond(
            200,
            {
                "message": "Deleted orders summary generated ({} order(s))".format(
                    len(sections)
                ),
                "url": url,
            },
        )
    except Exception as e:
        return respond(500, {"error": str(e)})
