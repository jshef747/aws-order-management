#!/usr/bin/env python3
"""
deploy.py — AWS Learner Lab sync/deploy script (Windows + macOS).

Run it, paste the credentials block from Learner Lab (AWS Details -> AWS CLI),
and it provisions / updates the whole Order Management System in YOUR account:

  - DynamoDB table 'orders' (PK orderId + GSI gsi-by-date)
  - All Lambda functions found in the lambdas/ folder

Idempotent: safe to re-run any time, in either partner's Learner Lab.

IMPORTANT (project rule): whenever the architecture changes — new Lambda,
Step Functions, SNS, S3, API Gateway, etc. — this script must be updated in
the same change so a single run always recreates the complete current system.
New Lambdas are picked up automatically from lambdas/; other resources need
their own idempotent step added below.

Usage:  python deploy.py    (Windows)
        python3 deploy.py   (macOS)
"""

import io
import os
import re
import subprocess
import sys
import time
import zipfile

REGION = "us-east-1"
TABLE_NAME = "orders"
GSI_NAME = "gsi-by-date"
LAMBDA_RUNTIME = "python3.12"
LAMBDA_TIMEOUT = 30
LAMBDAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lambdas")

OK = "[OK]"
FAIL = "[X]"


# ---------------------------------------------------------------- bootstrap
def ensure_boto3():
    try:
        import boto3  # noqa: F401
    except ImportError:
        print("boto3 not found — installing it now (one-time setup)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "boto3"])
        print(f"{OK} boto3 installed\n")


# ---------------------------------------------------------------- credentials
def read_credentials():
    print("=" * 62)
    print(" AWS Learner Lab deploy script")
    print("=" * 62)
    print("""
1. Start your Learner Lab and wait for the green dot.
2. Click 'AWS Details' -> next to 'AWS CLI' click 'Show'.
3. Copy the WHOLE block (starts with [default]).
4. Paste it below, then press Enter on an empty line.
""")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "" and lines:
            break
        if line.strip():
            lines.append(line)

    blob = "\n".join(lines)

    def grab(key):
        m = re.search(rf"{key}\s*=\s*(\S+)", blob)
        return m.group(1) if m else None

    access_key = grab("aws_access_key_id")
    secret_key = grab("aws_secret_access_key")
    session_token = grab("aws_session_token")

    if not (access_key and secret_key and session_token):
        print(f"\n{FAIL} Could not parse the credentials block. Make sure you copied")
        print("    the full text including aws_access_key_id, aws_secret_access_key")
        print("    and aws_session_token, then run the script again.")
        sys.exit(1)

    return access_key, secret_key, session_token


# ---------------------------------------------------------------- resources
def ensure_table(dynamodb):
    try:
        dynamodb.create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "orderId", "AttributeType": "S"},
                {"AttributeName": "gsiPk", "AttributeType": "S"},
                {"AttributeName": "creationDate", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": GSI_NAME,
                    "KeySchema": [
                        {"AttributeName": "gsiPk", "KeyType": "HASH"},
                        {"AttributeName": "creationDate", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        print(f"  Creating table '{TABLE_NAME}' (waiting until ACTIVE)...")
        dynamodb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
        print(f"{OK} DynamoDB table '{TABLE_NAME}' created")
    except dynamodb.exceptions.ResourceInUseException:
        print(f"{OK} DynamoDB table '{TABLE_NAME}' already exists")


def get_lab_role_arn(iam):
    role = iam.get_role(RoleName="LabRole")
    arn = role["Role"]["Arn"]
    print(f"{OK} Using IAM role LabRole ({arn})")
    return arn


def zip_lambda(path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(path, arcname="lambda_function.py")
    return buf.getvalue()


def deploy_lambdas(lambda_client, role_arn):
    env = {"Variables": {"ORDERS_TABLE": TABLE_NAME}}
    files = sorted(f for f in os.listdir(LAMBDAS_DIR) if f.endswith(".py"))
    if not files:
        print(f"{FAIL} No .py files found in {LAMBDAS_DIR}")
        sys.exit(1)

    for fname in files:
        name = fname[:-3]  # createOrder.py -> createOrder
        code = zip_lambda(os.path.join(LAMBDAS_DIR, fname))
        try:
            lambda_client.get_function(FunctionName=name)
            lambda_client.update_function_code(FunctionName=name, ZipFile=code)
            lambda_client.get_waiter("function_updated").wait(FunctionName=name)
            lambda_client.update_function_configuration(
                FunctionName=name,
                Runtime=LAMBDA_RUNTIME,
                Role=role_arn,
                Handler="lambda_function.lambda_handler",
                Timeout=LAMBDA_TIMEOUT,
                Environment=env,
            )
            lambda_client.get_waiter("function_updated").wait(FunctionName=name)
            print(f"{OK} Lambda '{name}' updated")
        except lambda_client.exceptions.ResourceNotFoundException:
            lambda_client.create_function(
                FunctionName=name,
                Runtime=LAMBDA_RUNTIME,
                Role=role_arn,
                Handler="lambda_function.lambda_handler",
                Code={"ZipFile": code},
                Timeout=LAMBDA_TIMEOUT,
                Environment=env,
            )
            lambda_client.get_waiter("function_active").wait(FunctionName=name)
            print(f"{OK} Lambda '{name}' created")


# ---------------------------------------------------------------- smoke test
def smoke_test(lambda_client):
    import json

    print("\nRunning smoke test...")
    create_event = {"body": json.dumps({"price": 9.99, "description": "deploy.py smoke test order"})}
    resp = lambda_client.invoke(FunctionName="createOrder", Payload=json.dumps(create_event))
    payload = json.loads(resp["Payload"].read())
    if payload.get("statusCode") != 201:
        print(f"{FAIL} createOrder smoke test failed: {payload}")
        sys.exit(1)
    order = json.loads(payload["body"])["order"]
    print(f"{OK} createOrder works (orderId={order['orderId']})")

    resp = lambda_client.invoke(FunctionName="getAllOrders", Payload=json.dumps({}))
    payload = json.loads(resp["Payload"].read())
    if payload.get("statusCode") != 200:
        print(f"{FAIL} getAllOrders smoke test failed: {payload}")
        sys.exit(1)
    count = json.loads(payload["body"])["count"]
    print(f"{OK} getAllOrders works ({count} order(s) in table, sorted by creation date)")

    # Clean up the smoke-test order so the table stays tidy.
    delete_event = {"pathParameters": {"id": order["orderId"]}}
    resp = lambda_client.invoke(FunctionName="deleteOrder", Payload=json.dumps(delete_event))
    payload = json.loads(resp["Payload"].read())
    if payload.get("statusCode") == 200:
        print(f"{OK} deleteOrder works (smoke test order removed)")
    else:
        print(f"{FAIL} deleteOrder smoke test failed: {payload}")
        sys.exit(1)


# ---------------------------------------------------------------- main
def main():
    ensure_boto3()
    import boto3

    access_key, secret_key, session_token = read_credentials()

    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token,
        region_name=REGION,
    )

    try:
        identity = session.client("sts").get_caller_identity()
        print(f"\n{OK} Connected to AWS account {identity['Account']} ({REGION})\n")
    except Exception as e:
        print(f"\n{FAIL} Could not connect to AWS: {e}")
        print("    Credentials may have expired — restart the lab and copy fresh ones.")
        sys.exit(1)

    dynamodb = session.client("dynamodb")
    iam = session.client("iam")
    lambda_client = session.client("lambda")

    ensure_table(dynamodb)
    role_arn = get_lab_role_arn(iam)
    deploy_lambdas(lambda_client, role_arn)
    smoke_test(lambda_client)

    print("\n" + "=" * 62)
    print(" Deployment complete — your Learner Lab is in sync.")
    print("=" * 62)


if __name__ == "__main__":
    main()
