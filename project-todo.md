# Project TODO — Order Management System

Last updated: 2026-06-13

---

## Done

### Infrastructure & Core
- [x] DynamoDB table `orders` — PK `orderId` (UUID), GSI `gsi-by-date` (gsiPk + creationDate)
- [x] API Gateway `orders-api` (stage `prod`) — 10 routes + CORS OPTIONS on every path
- [x] `deploy.py` — single idempotent deploy script, `--auto` mode for non-interactive credential use

### Lambda Functions
- [x] `createOrder` — POST /orders
- [x] `getAllOrders` — GET /orders (sorted via GSI)
- [x] `getOrder` — GET /orders/{id}
- [x] `updateOrder` — PUT /orders/{id}
- [x] `deleteOrder` — DELETE /orders/{id} + fire-and-forget Step Functions StartExecution
- [x] `subscribeNotification` — POST /subscribe (SNS email subscribe, returns subscriptionArn)
- [x] `unsubscribeNotification` — DELETE /unsubscribe (SNS unsubscribe by ARN)
- [x] `backupOrder` — internal (Step Functions → writes order-{orderId}.txt to S3)
- [x] `generatePdfSummary` — GET /generate-pdf (reads all .txt from S3, builds reportlab PDF, returns presigned URL)
- [x] `analyzeImage` — POST /analyze-image (Rekognition detect_labels — freestyle feature)

### Event-driven Architecture
- [x] SNS topic `order-deleted` — provisioned in deploy.py (`ensure_sns_topic`)
- [x] S3 bucket `order-backups-{accountId}` — provisioned in deploy.py (`ensure_s3_bucket`)
- [x] Step Functions state machine `delete-order-fanout` — parallel branches: SNS Publish + backupOrder Lambda invoke
- [x] reportlab bundled into generatePdfSummary deployment package via `zip_lambda(with_reportlab=True)`

### Frontend
- [x] `client.html` — Amazon-style storefront; full CRUD, subscribe/unsubscribe, PDF download, Rekognition image analysis

### Smoke test (deploy.py)
- [x] Extend `smoke_test()` to cover `subscribeNotification` (assert 201, capture PendingConfirmation ARN), `unsubscribeNotification` (assert 200), and `generatePdfSummary` (assert 200 + non-empty `https://` `url`); inserted between deleteOrder and final completion print

### AWS Amplify hosting (required for submission)
- [x] `ensure_amplify()` in deploy.py — `AMPLIFY_APP_NAME = 'order-management-client'`, idempotent app lookup/create, `main` branch, zip `client.html` as `index.html`, direct zip upload via create_deployment → PUT → start_deployment, prints live URL
- [x] Amplify client wired into `main()` and `ensure_amplify(amplify, invoke_url)` called after `smoke_test()`, printing the Amplify URL prominently for submission

### CLAUDE.md status section
- [x] Updated the `## Status` block — Done: everything (all 11 Lambdas, SNS, S3, Step Functions, API Gateway, client.html, Amplify); Remaining: none — project complete

---

## Remaining

_None — project complete._

---

## Not in scope

- Amplify custom domain (default `*.amplifyapp.com` is sufficient)
- SNS email confirmation is manual by design (AWS requires the subscriber to click the confirmation link)
- Step Functions execution history verification in smoke test (would require polling; out of scope for a deploy-time check)
