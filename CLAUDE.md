# CLAUDE.md

AWS course final project — event-driven serverless Order Management System.
Two partners, each with a **separate AWS Learner Lab** (credentials rotate every session).
Full design: open `architecture.html` in a browser.

## Project rule (most important)

**`deploy.py` is the single source of truth for provisioning.** Any architecture change —
new Lambda, Step Functions, SNS, S3, API Gateway route, etc. — MUST update `deploy.py` in
the same commit, so either partner can paste fresh credentials, run it once, and get the
complete current system. Lambdas in `lambdas/` are picked up automatically; new endpoints go
in the `API_ROUTES` dict; other resource types need their own idempotent step.

## Learner Lab constraints

- Region is always `us-east-1`; execution role is always `LabRole` (cannot create roles).
- Service permissions are restricted. Probed results:
  **ALLOWED:** Rekognition, Textract. **DENIED:** Translate, Comprehend, Polly, Lex.
  The freestyle feature is therefore Rekognition (`analyzeImage`), not Translate.
- Deploy/test: `python3 deploy.py`, paste the credentials block from
  Learner Lab → AWS Details → AWS CLI → Show. Idempotent, safe to re-run.

## Code conventions (see lambdas/createOrder.py as the reference)

- One Lambda per endpoint, Python 3.12, handler `lambda_function.lambda_handler`
  (deploy.py zips each file under that name).
- API-Gateway-proxy shape: parse `event["body"]` / `event["pathParameters"]`,
  return via `respond(status, body)` with the shared CORS `HEADERS` dict.
- DynamoDB via `boto3.resource`; table name from env `ORDERS_TABLE` (default `orders`);
  prices stored as `Decimal`, serialized to float with `to_plain()` before returning.
- `orders` table: PK `orderId` (UUID). GSI `gsi-by-date` (`gsiPk="ORDER"` + `creationDate`)
  → sorted "get all" via Query, never Scan.
- Errors: 400 bad input, 404 not found, 500 catch-all `{"error": ...}`.

## Testing

- Local mock tests: patch `boto3.resource`/`boto3.client` with fakes, invoke
  `lambda_handler` directly, assert statusCodes (see git history for examples).
- `python3 -m py_compile deploy.py lambdas/*.py` before every commit.
- `deploy.py` ends with a smoke test (create → list → update → HTTPS via API GW → delete).

## Status

Done: CRUD Lambdas (create/getAll/get/update/delete), DynamoDB table, API Gateway
(`orders-api`, stage `prod`), deploy script.
Remaining: SNS subscribe/unsubscribe · Step Functions delete fan-out + backupOrder ·
S3 backups + PDF summary (`generatePdfSummary`) · Rekognition `analyzeImage` · Amplify
web client. `deleteOrder` has a placeholder comment where `StartExecution` goes.
