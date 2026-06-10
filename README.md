# Event-Driven Serverless Order Management System

AWS course final project. Architecture overview: open `architecture.html` in a browser.

## Deploying to your Learner Lab

Both partners work in separate AWS Learner Labs whose credentials rotate every session.
`deploy.py` syncs the complete current system into whichever account runs it.

1. Start your Learner Lab and wait for the green dot.
2. Click **AWS Details** → next to **AWS CLI** click **Show**, copy the whole block
   (starts with `[default]`).
3. Run the script:
   - **Windows:** `python deploy.py`
   - **Mac:** `python3 deploy.py`
4. Paste the credentials block, press Enter on an empty line.

The script (idempotent — safe to re-run any time):
- installs `boto3` automatically if missing,
- creates the DynamoDB `orders` table (PK `orderId` + GSI `gsi-by-date`) if needed,
- creates/updates every Lambda in `lambdas/` (runtime Python 3.12, role `LabRole`),
- creates/updates the `orders-api` REST API (API Gateway, stage `prod`, CORS enabled)
  and prints the invoke URL,
- runs a smoke test (create → list → update → call the API over HTTPS → delete) and
  prints the results.

## API endpoints

Base URL: `https://<api-id>.execute-api.us-east-1.amazonaws.com/prod` (printed by deploy.py)

| Method | Path | Lambda | Body |
|---|---|---|---|
| POST | /orders | createOrder | `{"price": 9.99, "description": "..."}` |
| GET | /orders | getAllOrders | — |
| GET | /orders/{id} | getOrder | — |
| PUT | /orders/{id} | updateOrder | `{"price"?: 9.99, "description"?: "..."}` |
| DELETE | /orders/{id} | deleteOrder | — |
| POST | /analyze-image | analyzeImage | `{"image": "<base64 JPEG/PNG>"}` |

## Project rule

**Whenever the architecture changes (new Lambda, Step Functions, SNS, S3, API Gateway, ...),
`deploy.py` must be updated in the same commit.** One run of the script must always produce
the complete, current system. New Lambdas in `lambdas/` are picked up automatically; other
resource types need their own idempotent step in the script.

## Current contents

| Path | What it is |
|---|---|
| `lambdas/createOrder.py` | POST /orders — create order (UUID id, ISO dates) |
| `lambdas/getAllOrders.py` | GET /orders — all orders sorted by creation date (GSI query) |
| `lambdas/getOrder.py` | GET /orders/{id} — single order |
| `lambdas/updateOrder.py` | PUT /orders/{id} — update price/description |
| `lambdas/deleteOrder.py` | DELETE /orders/{id} — delete (Step Functions hand-off comes later) |
| `lambdas/analyzeImage.py` | POST /analyze-image — Rekognition labels → suggested description (freestyle) |
| `deploy.py` | Cross-platform Learner Lab sync/deploy script |
| `architecture.html` | Full architecture diagram + unified graph |
| `Docs/` | Assignment PDF |

## Upcoming phases

SNS topic + subscribe/unsubscribe APIs · Step Functions delete fan-out + backupOrder ·
S3 backups + PDF summary · Amplify web client.

(Freestyle note: Amazon Translate is not permitted by the Learner Lab's LabRole, so the
freestyle feature uses Amazon Rekognition instead — implemented as `analyzeImage`.)
