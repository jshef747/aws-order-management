#!/usr/bin/env python3
"""
update_amplify.py — redeploy ONLY the web client (client.html) to AWS Amplify.

Use this when you changed client.html and just want to push it live, without
re-running the full deploy.py (Lambdas, API Gateway, DynamoDB, SNS, S3, Step
Functions are all left untouched).

It reuses deploy.py's credential parsing and Amplify deployment logic, so
deploy.py stays the single source of truth for how the app is built.

Usage:  python  update_amplify.py          (paste the Learner Lab creds block)
        python3 update_amplify.py
        python3 update_amplify.py --auto    (read creds from AWS_* env vars)
"""

import os
import sys

import deploy  # importing runs only definitions (main is __main__-guarded) — no side effects


def resolve_invoke_url(apigw):
    """Build the orders-api invoke URL from API Gateway.

    Only needed when the Amplify app must be created for the first time (it is
    stored as the app's API_URL env var). On a normal update the app already
    exists and ensure_amplify ignores this value. Returns "" if not found.
    """
    apis = apigw.get_rest_apis().get("items", [])
    api = next((a for a in apis if a["name"] == deploy.API_NAME), None)
    if not api:
        return ""
    return f"https://{api['id']}.execute-api.{deploy.REGION}.amazonaws.com/{deploy.API_STAGE}"


def main():
    deploy.ensure_boto3()
    import boto3

    if "--auto" in sys.argv:
        access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        session_token = os.environ.get("AWS_SESSION_TOKEN")
        if not (access_key and secret_key and session_token):
            print(f"{deploy.FAIL} --auto requires AWS_ACCESS_KEY_ID, "
                  "AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN env vars.")
            sys.exit(1)
        print(f"{deploy.OK} Using credentials from environment (--auto mode)\n")
    else:
        access_key, secret_key, session_token = deploy.read_credentials()

    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token,
        region_name=deploy.REGION,
    )

    try:
        identity = session.client("sts").get_caller_identity()
        print(f"\n{deploy.OK} Connected to AWS account {identity['Account']} ({deploy.REGION})\n")
    except Exception as e:
        print(f"\n{deploy.FAIL} Could not connect to AWS: {e}")
        print("    Credentials may have expired — restart the lab and copy fresh ones.")
        sys.exit(1)

    invoke_url = resolve_invoke_url(session.client("apigateway"))
    amplify_url = deploy.ensure_amplify(session.client("amplify"), invoke_url)

    print("\n" + "=" * 62)
    print(f" Web client redeployed (Amplify): {amplify_url}")
    print("=" * 62)


if __name__ == "__main__":
    main()
