# MediNotes Pro

Portfolio demo: AI consultation notes with **Next.js**, **FastAPI**, **Clerk**, and a near-zero-cost **AWS** deployment (container on **Lambda** + **ECR**, **DynamoDB**, **S3**, **CloudWatch**).

**Demo:** [https://r22xttnd3dw6woagtzx7vwifrm0xupqv.lambda-url.us-west-2.on.aws/](https://r22xttnd3dw6woagtzx7vwifrm0xupqv.lambda-url.us-west-2.on.aws/)

> Demo only — not for real PHI or clinical use.

**Live pattern:** static Next.js export served by FastAPI inside a Docker image → Amazon ECR → AWS Lambda (Lambda Web Adapter) → Function URL with `RESPONSE_STREAM` for SSE.

## Why this architecture

| Choice | Rationale |
| --- | --- |
| Lambda + container (not ECS Express) | Cheaper and simpler for a study/portfolio workload; pay per invoke |
| DynamoDB on-demand (not RDS) | Serverless, free-tier friendly, no always-on database cost |
| S3 for exports | Private objects + short-lived presigned URLs; 7-day lifecycle |
| Upstash Redis | Free-tier daily rate limits so OpenAI spend cannot runaway |
| Clerk | Auth, sessions, and plan gating (`Protect`) without building IAM/Cognito UI |

## Architecture

```text
Browser (Clerk session)
    │  JWT on API calls
    ▼
Lambda Function URL  ──RESPONSE_STREAM──►  FastAPI (uvicorn)
    │                                         │
    │                              ┌──────────┼──────────┐
    │                              ▼          ▼          ▼
    │                           OpenAI     DynamoDB     S3
    │                         (stream)    (visits +    (md/pdf
    │                                      usage)      exports)
    │                              ▼
    │                           Upstash
    │                         (rate limit)
    ▼
CloudWatch Logs

GitHub Actions (OIDC) → ECR push → lambda update-function-code
```

**Auth & permissions:** Clerk issues JWTs; FastAPI validates them via JWKS (`fastapi-clerk-auth`). The product UI is wrapped in Clerk `<Protect plan="premium_subscription">` for entitlement checks.

**LLM flow:** `POST /api/consultation` streams markdown over SSE, then persists the visit (notes + summary + model/prompt metadata + token counts) to DynamoDB.

**Exports:** `POST /api/exports` writes Markdown or PDF under `exports/{user}/{visit}/…` and returns a presigned GET URL.

## Cost table (study / low traffic)

| Service | Expected monthly cost | Notes |
| --- | --- | --- |
| AWS Lambda | ~$0 | Free tier covers light demos; 1024 MB / 300s max |
| Amazon ECR | Cents | One small image; lifecycle unused tags if needed |
| DynamoDB on-demand | ~$0 | Free tier / pennies at demo volume |
| S3 | ~$0 | Tiny exports + 7-day expiry |
| CloudWatch Logs | ~$0 | Stay in free tier; avoid verbose debug in prod |
| Clerk | $0 | Development instance for portfolio |
| Upstash Redis | $0 | Free tier REST API |
| OpenAI API | **Variable** | Real cost driver — mitigated by daily rate limit |

Avoided on purpose: RDS, ECS/Fargate, ALB, NAT gateway (always-on cost).

## Threat model (blurb)

| Threat | Mitigation |
| --- | --- |
| Stolen session / API abuse | Clerk JWT required on `/api/*`; daily per-user rate limit |
| Open Function URL | Public URL is intentional for a static+API demo; authorization is application-level (JWT), not Lambda IAM auth |
| Data exfiltration via export links | S3 block public access; SSE-S3; short-lived presigned URLs |
| Prompt/model drift | `PROMPT_VERSION` + `MODEL_NAME` stored on each visit |
| Secrets in git | `.env*` gitignored; runtime secrets in Lambda env / GitHub Actions secrets; CI uses OIDC (no long-lived AWS keys) |
| PHI exposure | Demo disclaimer; do not use real patient data |

This is **not** HIPAA-compliant as deployed (no BAA stack, shared demo keys, public Function URL). Treat as an engineering showcase.

## Repository layout

```text
api/                 FastAPI app (SSE, DynamoDB, S3, rate limit)
pages/               Next.js pages (static export)
infra/template.yaml  SAM/CloudFormation reference
.github/workflows/   OIDC → ECR → Lambda deploy
Dockerfile           Multi-stage: Next build + Python/Lambda Web Adapter
```

## Local development

### Frontend only

```bash
cp .env.example .env.local
npm install
npm run dev
```

API calls to `/api/*` need the FastAPI process (below) or a deployed backend.

### API (from repo root)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=.
export CLERK_JWKS_URL=...
export OPENAI_API_KEY=...
export DYNAMODB_TABLE=consultation-app
export S3_EXPORTS_BUCKET=consultation-app-exports-890886303710
export UPSTASH_REDIS_REST_URL=...
export UPSTASH_REDIS_REST_TOKEN=...
uvicorn api.server:app --reload --port 8000
```

### Full container

```bash
docker build \
  --build-arg NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_... \
  -t consultation-app .
docker run --rm -p 8000:8000 --env-file .env consultation-app
```

## AWS + GitHub deploy

Stack naming used in this repo:

- Region: `us-west-2`
- ECR + Lambda: `consultation-app`
- DynamoDB: `consultation-app`
- S3: `consultation-app-exports-<accountId>`
- GitHub OIDC role: `github-actions-consultation-app`

### GitHub configuration

**Variables:** `AWS_REGION`, `AWS_ROLE_ARN`, `ECR_REPOSITORY`, `LAMBDA_FUNCTION_NAME`  
**Secrets:** `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_JWKS_URL`, `OPENAI_API_KEY`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`

Push to `main` runs [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml).

### Infrastructure as Code

[`infra/template.yaml`](infra/template.yaml) documents DynamoDB, S3, IAM, Lambda (image), and Function URL (`RESPONSE_STREAM`). Resources were bootstrapped to match this template; use SAM for greenfield recreates:

```bash
cd infra
sam build
sam deploy --guided
```

## API surface

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | No | Health + model/prompt metadata |
| POST | `/api/consultation` | Clerk JWT | Stream summary; persist visit |
| GET | `/api/visits` | Clerk JWT | Visit history |
| GET | `/api/usage` | Clerk JWT | Per-day token/request counters |
| POST | `/api/exports` | Clerk JWT | Markdown/PDF → S3 presigned URL |
