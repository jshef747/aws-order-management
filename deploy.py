#!/usr/bin/env python3
"""
deploy.py — AWS Learner Lab sync/deploy script (Windows + macOS).

Run it, paste the credentials block from Learner Lab (AWS Details -> AWS CLI),
and it provisions / updates the whole Order Management System in YOUR account:

  - DynamoDB table 'orders' (PK orderId + GSI gsi-by-date)
  - All Lambda functions found in the lambdas/ folder
  - API Gateway REST API 'orders-api' (stage 'prod') routing every endpoint

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
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

REGION = "us-east-1"
TABLE_NAME = "orders"
GSI_NAME = "gsi-by-date"
LAMBDA_RUNTIME = "python3.12"
LAMBDA_TIMEOUT = 30
LAMBDAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lambdas")

# New resource names (single source of truth for provisioning).
SNS_TOPIC_NAME = "order-deleted"
BACKUP_BUCKET_NAME = "order-backups"
STATE_MACHINE_NAME = "delete-order-fanout"

API_NAME = "orders-api"
API_STAGE = "prod"

# Route table: path -> {HTTP method -> Lambda name}. Every architecture change that
# adds/changes an endpoint must be reflected here (project rule).
API_ROUTES = {
    "/orders": {"POST": "createOrder", "GET": "getAllOrders"},
    "/orders/{id}": {"GET": "getOrder", "PUT": "updateOrder", "DELETE": "deleteOrder"},
    "/analyze-image": {"POST": "analyzeImage"},
    "/subscribe": {"POST": "subscribeNotification"},
    "/unsubscribe": {"DELETE": "unsubscribeNotification"},
    "/generate-pdf": {"GET": "generatePdfSummary"},
}

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


def ensure_sns_topic(sns):
    # create_topic is idempotent: returns the existing ARN if the topic exists.
    resp = sns.create_topic(Name=SNS_TOPIC_NAME)
    topic_arn = resp["TopicArn"]
    print(f"{OK} SNS topic '{SNS_TOPIC_NAME}' ready ({topic_arn})")
    return topic_arn


def ensure_s3_bucket(s3, account_id):
    # S3 bucket names are GLOBALLY unique, so suffix the account id to avoid
    # collisions with buckets owned by other accounts (the bare name
    # 'order-backups' is already taken globally).
    bucket_name = f"{BACKUP_BUCKET_NAME}-{account_id}"
    try:
        # us-east-1 must NOT pass a LocationConstraint.
        s3.create_bucket(Bucket=bucket_name)
        print(f"{OK} S3 bucket '{bucket_name}' created")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"{OK} S3 bucket '{bucket_name}' already exists (owned by you)")
    except s3.exceptions.BucketAlreadyExists:
        print(f"{OK} S3 bucket '{bucket_name}' already exists")
    return bucket_name


def ensure_state_machine(sfn, role_arn, topic_arn, account_id):
    backup_fn_arn = f"arn:aws:lambda:{REGION}:{account_id}:function:backupOrder"
    asl = {
        "Comment": "Fan out a deleted order to SNS notification and S3 backup in parallel.",
        "StartAt": "FanOut",
        "States": {
            "FanOut": {
                "Type": "Parallel",
                "End": True,
                "Branches": [
                    {
                        "StartAt": "NotifyDeleted",
                        "States": {
                            "NotifyDeleted": {
                                "Type": "Task",
                                "Resource": "arn:aws:states:::sns:publish",
                                "Parameters": {
                                    "TopicArn": topic_arn,
                                    "Message.$": "States.JsonToString($)",
                                },
                                "End": True,
                            }
                        },
                    },
                    {
                        "StartAt": "BackupOrder",
                        "States": {
                            "BackupOrder": {
                                "Type": "Task",
                                "Resource": "arn:aws:states:::lambda:invoke",
                                "Parameters": {
                                    "FunctionName": backup_fn_arn,
                                    "Payload.$": "$",
                                },
                                "End": True,
                            }
                        },
                    },
                ],
            }
        },
    }
    definition = json.dumps(asl)
    try:
        resp = sfn.create_state_machine(
            name=STATE_MACHINE_NAME,
            definition=definition,
            roleArn=role_arn,
            type="STANDARD",
        )
        sm_arn = resp["stateMachineArn"]
        print(f"{OK} State machine '{STATE_MACHINE_NAME}' created ({sm_arn})")
    except sfn.exceptions.StateMachineAlreadyExists:
        machines = sfn.list_state_machines(maxResults=1000)["stateMachines"]
        sm = next((m for m in machines if m["name"] == STATE_MACHINE_NAME), None)
        sm_arn = sm["stateMachineArn"]
        sfn.update_state_machine(
            stateMachineArn=sm_arn,
            definition=definition,
            roleArn=role_arn,
        )
        print(f"{OK} State machine '{STATE_MACHINE_NAME}' updated ({sm_arn})")
    return sm_arn


def get_lab_role_arn(iam):
    role = iam.get_role(RoleName="LabRole")
    arn = role["Role"]["Arn"]
    print(f"{OK} Using IAM role LabRole ({arn})")
    return arn


def zip_lambda(path, with_reportlab=False):
    if not with_reportlab:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(path, arcname="lambda_function.py")
        return buf.getvalue()

    # generatePdfSummary needs reportlab bundled into the deployment package.
    tmpdir = tempfile.mkdtemp(prefix="pdflambda_")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "reportlab", "-t", tmpdir]
        )
        shutil.copyfile(path, os.path.join(tmpdir, "lambda_function.py"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(tmpdir):
                for fn in files:
                    full = os.path.join(root, fn)
                    arc = os.path.relpath(full, tmpdir)
                    zf.write(full, arcname=arc)
        return buf.getvalue()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def deploy_lambdas(lambda_client, role_arn, fanout_arn=None, topic_arn=None, backup_bucket=None):
    variables = {"ORDERS_TABLE": TABLE_NAME}
    if fanout_arn:
        variables["FANOUT_STATE_MACHINE_ARN"] = fanout_arn
    if topic_arn:
        variables["ORDER_DELETED_TOPIC_ARN"] = topic_arn
    if backup_bucket:
        variables["BACKUP_BUCKET"] = backup_bucket
    env = {"Variables": variables}
    files = sorted(f for f in os.listdir(LAMBDAS_DIR) if f.endswith(".py"))
    if not files:
        print(f"{FAIL} No .py files found in {LAMBDAS_DIR}")
        sys.exit(1)

    for fname in files:
        name = fname[:-3]  # createOrder.py -> createOrder
        code = zip_lambda(
            os.path.join(LAMBDAS_DIR, fname),
            with_reportlab=(name == "generatePdfSummary"),
        )
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


# ---------------------------------------------------------------- API Gateway
def ensure_rest_api(apigw, lambda_client, account_id):
    apis = apigw.get_rest_apis(limit=500)["items"]
    api = next((a for a in apis if a["name"] == API_NAME), None)
    if api:
        api_id = api["id"]
        print(f"{OK} REST API '{API_NAME}' already exists (id={api_id})")
    else:
        api = apigw.create_rest_api(
            name=API_NAME,
            description="Order Management System REST API",
            endpointConfiguration={"types": ["REGIONAL"]},
        )
        api_id = api["id"]
        print(f"{OK} REST API '{API_NAME}' created (id={api_id})")

    # Map existing resource paths -> resource ids.
    resources = apigw.get_resources(restApiId=api_id, limit=500)["items"]
    by_path = {r["path"]: r["id"] for r in resources}

    def ensure_resource(path):
        if path in by_path:
            return by_path[path]
        parent_path = path.rsplit("/", 1)[0] or "/"
        part = path.rsplit("/", 1)[1]
        parent_id = ensure_resource(parent_path) if parent_path != "/" else by_path["/"]
        res = apigw.create_resource(restApiId=api_id, parentId=parent_id, pathPart=part)
        by_path[path] = res["id"]
        return res["id"]

    def existing_methods(resource_id):
        res = apigw.get_resource(restApiId=api_id, resourceId=resource_id)
        return set((res.get("resourceMethods") or {}).keys())

    for path, methods in API_ROUTES.items():
        resource_id = ensure_resource(path)
        have = existing_methods(resource_id)

        for http_method, fn_name in methods.items():
            if http_method in have:
                continue
            apigw.put_method(
                restApiId=api_id,
                resourceId=resource_id,
                httpMethod=http_method,
                authorizationType="NONE",
            )
            fn_arn = f"arn:aws:lambda:{REGION}:{account_id}:function:{fn_name}"
            apigw.put_integration(
                restApiId=api_id,
                resourceId=resource_id,
                httpMethod=http_method,
                type="AWS_PROXY",
                integrationHttpMethod="POST",
                uri=f"arn:aws:apigateway:{REGION}:lambda:path/2015-03-31/functions/{fn_arn}/invocations",
            )
            print(f"{OK} Route {http_method} {path} -> {fn_name}")

        if "OPTIONS" not in have:
            add_cors_options(apigw, api_id, resource_id, methods)
            print(f"{OK} CORS (OPTIONS) enabled on {path}")

    # Allow this API to invoke each Lambda (idempotent via fixed statement id).
    for methods in API_ROUTES.values():
        for fn_name in set(methods.values()):
            try:
                lambda_client.add_permission(
                    FunctionName=fn_name,
                    StatementId="apigateway-invoke",
                    Action="lambda:InvokeFunction",
                    Principal="apigateway.amazonaws.com",
                    SourceArn=f"arn:aws:execute-api:{REGION}:{account_id}:{api_id}/*",
                )
            except lambda_client.exceptions.ResourceConflictException:
                pass

    # Deploy on every run so route changes always reach the stage.
    apigw.create_deployment(restApiId=api_id, stageName=API_STAGE)
    invoke_url = f"https://{api_id}.execute-api.{REGION}.amazonaws.com/{API_STAGE}"
    print(f"{OK} API deployed to stage '{API_STAGE}'")
    print(f"\n    Invoke URL: {invoke_url}\n")
    return invoke_url


def add_cors_options(apigw, api_id, resource_id, methods):
    allow_methods = ",".join(sorted(set(methods) | {"OPTIONS"}))
    apigw.put_method(
        restApiId=api_id,
        resourceId=resource_id,
        httpMethod="OPTIONS",
        authorizationType="NONE",
    )
    apigw.put_integration(
        restApiId=api_id,
        resourceId=resource_id,
        httpMethod="OPTIONS",
        type="MOCK",
        requestTemplates={"application/json": '{"statusCode": 200}'},
    )
    apigw.put_method_response(
        restApiId=api_id,
        resourceId=resource_id,
        httpMethod="OPTIONS",
        statusCode="200",
        responseParameters={
            "method.response.header.Access-Control-Allow-Origin": True,
            "method.response.header.Access-Control-Allow-Headers": True,
            "method.response.header.Access-Control-Allow-Methods": True,
        },
    )
    apigw.put_integration_response(
        restApiId=api_id,
        resourceId=resource_id,
        httpMethod="OPTIONS",
        statusCode="200",
        responseParameters={
            "method.response.header.Access-Control-Allow-Origin": "'*'",
            "method.response.header.Access-Control-Allow-Headers": "'Content-Type'",
            "method.response.header.Access-Control-Allow-Methods": f"'{allow_methods}'",
        },
    )


# ---------------------------------------------------------------- smoke test
def smoke_test(lambda_client, invoke_url):
    import urllib.request

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

    update_event = {
        "pathParameters": {"id": order["orderId"]},
        "body": json.dumps({"description": "deploy.py smoke test order (updated)"}),
    }
    resp = lambda_client.invoke(FunctionName="updateOrder", Payload=json.dumps(update_event))
    payload = json.loads(resp["Payload"].read())
    if payload.get("statusCode") != 200:
        print(f"{FAIL} updateOrder smoke test failed: {payload}")
        sys.exit(1)
    print(f"{OK} updateOrder works (description updated)")

    # One real HTTPS request to prove API Gateway routes end to end.
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(f"{invoke_url}/orders", timeout=15, context=ctx) as r:
            api_body = json.loads(r.read())
        print(f"{OK} API Gateway works (GET {invoke_url}/orders -> {api_body['count']} order(s))")
    except Exception as e:
        print(f"{FAIL} API Gateway smoke test failed: {e}")
        sys.exit(1)

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

    if "--auto" in sys.argv:
        access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        session_token = os.environ.get("AWS_SESSION_TOKEN")
        if not (access_key and secret_key and session_token):
            print(f"{FAIL} --auto requires AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN env vars.")
            sys.exit(1)
        print(f"{OK} Using credentials from environment (--auto mode)\n")
    else:
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
    apigw = session.client("apigateway")
    sns = session.client("sns")
    s3 = session.client("s3")
    sfn = session.client("stepfunctions")

    ensure_table(dynamodb)
    role_arn = get_lab_role_arn(iam)

    # New resources first: SNS -> S3 -> Step Functions. The state machine
    # references backupOrder's ARN as a string; backupOrder is deployed by
    # deploy_lambdas below, which is fine since no execution runs yet.
    topic_arn = ensure_sns_topic(sns)
    backup_bucket = ensure_s3_bucket(s3, identity["Account"])
    fanout_arn = ensure_state_machine(sfn, role_arn, topic_arn, identity["Account"])

    deploy_lambdas(
        lambda_client,
        role_arn,
        fanout_arn=fanout_arn,
        topic_arn=topic_arn,
        backup_bucket=backup_bucket,
    )
    invoke_url = ensure_rest_api(apigw, lambda_client, identity["Account"])
    smoke_test(lambda_client, invoke_url)

    print("\n" + "=" * 62)
    print(" Deployment complete — your Learner Lab is in sync.")
    print("=" * 62)


if __name__ == "__main__":
    main()
