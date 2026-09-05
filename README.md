# CloudSight Intake

A production-shaped, fully serverless image-processing pipeline on AWS that stays
inside the **AWS Always-Free tier** in its default configuration.

Upload an image → S3 event → Lambda (X-Ray traced) → optional cascading Amazon
Rekognition → summary in DynamoDB + full JSON in S3 → SNS notification. Failed
async invocations land in an SQS dead-letter queue with a CloudWatch alarm, and a
CloudWatch dashboard tracks the whole thing.

---

## Architecture

```mermaid
flowchart LR
    U[User / Streamlit app] -- put_object --> IN[(S3 input bucket<br/>uploads/ · 7-day purge)]
    IN -- ObjectCreated<br/>.jpg .jpeg .png .gif --> L[Lambda processor<br/>Python 3.11 · 128 MB · 15 s<br/>X-Ray Active]
    L -- Query by ETag<br/>idempotency --> D[(DynamoDB<br/>image_id / timestamp<br/>StatusIndex GSI)]
    L -- DetectLabels → DetectText → DetectFaces --> R[Amazon Rekognition]
    L -- results/&lt;image_id&gt;.json --> OUT[(S3 output bucket)]
    L -- publish --> SNS[SNS topic] --> M[Email]
    L -. on failure .-> DLQ[[SQS DLQ]] --> A{{CloudWatch alarm}} --> SNS
    L -- metrics --> CW[CloudWatch dashboard]
    D -- metrics --> CW
```

### Request flow

1. The client writes `uploads/<name>` to the **input bucket**.
2. S3 fires an `ObjectCreated` event (suffix-filtered) that invokes the **Lambda**.
3. Lambda takes the S3 object **ETag as `image_id`** and `Query`s DynamoDB — if a
   row already exists the event is a duplicate and is skipped (idempotency).
4. If `USE_REKOGNITION=true`, it calls `detect_labels`, then `detect_text` (only
   if labels came back), then `detect_faces` (only if labels or text came back).
   Otherwise it records a `metadata-only` result. This gating caps Rekognition
   calls at 3 per image and usually fewer.
5. It writes a summary row to **DynamoDB** and the full result to
   `results/<image_id>.json` in the **output bucket**.
6. It publishes a success message to **SNS**. Any exception is published as a
   failure message and then re-raised so Lambda's async retry (2 attempts) and
   finally the **SQS DLQ** take over. The DLQ alarm notifies the same SNS topic.
7. Every call is captured as an **X-Ray** trace (segments for S3, DynamoDB, SNS,
   Rekognition via `patch_all()`).

---

## Repository layout

```
terraform/        IaC — split into main.tf / variables.tf / outputs.tf / backend.tf
lambda/           index.py (handler) + requirements.txt (xray sdk only)
app/              Streamlit front end
scripts/          build_lambda.sh — the single Lambda packager (TF + CI both call it)
tests/            pytest + moto unit tests for the handler
.github/workflows deploy.yml (lint→test→apply) · destroy.yml
```

---

## Free-tier cost breakdown

Default config = `use_rekognition = false`. At demo volumes the bill is **$0.00**.

| Service | This stack uses | Free allowance | Notes |
|---|---|---|---|
| Lambda | 128 MB, ≤15 s, a few invokes | 1M requests + 400,000 GB-s / month | **Always free** |
| DynamoDB | On-demand, tiny items | 25 GB storage | **Always free**; on-demand R/W here is fractions of a cent |
| SQS | 1 DLQ, near-zero traffic | 1M requests / month | **Always free** |
| SNS | Email notifications | 1,000 email notifications / month | **Always free** |
| CloudWatch | 1 dashboard, 1 alarm, Lambda logs | 3 dashboards, 10 alarms, 5 GB logs | **Always free** |
| X-Ray | Traces from each invoke | 100,000 traces recorded / month | **Always free** |
| S3 | 2 buckets, small objects, 7-day input purge | 5 GB, 20k GET, 2k PUT | **12 months only**, then ~$0.023/GB-mo |
| Rekognition | Only if `use_rekognition = true` | 5,000 images / month | **12 months only** — off by default |

Cost guardrails built in: input bucket purges `uploads/` after 7 days, logs
retain 7 days, DynamoDB is `PAY_PER_REQUEST`, Rekognition calls are gated and
opt-in.

---

## Prerequisites

- Terraform ≥ 1.5, Python 3.11, AWS CLI configured with credentials that can
  create the resources above.
- An email address for SNS (you'll get a subscription-confirmation email).

## Quickstart

```bash
git clone <your-repo-url> cloudsight-intake && cd cloudsight-intake

# 1. One-time remote-state bucket (S3 backend)
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws s3api create-bucket --bucket cloudsight-tfstate-$ACCOUNT --region us-east-1
aws s3api put-bucket-versioning --bucket cloudsight-tfstate-$ACCOUNT \
  --versioning-configuration Status=Enabled

# 2. Backend + vars
cd terraform
cp backend.hcl.example backend.hcl        # set bucket = cloudsight-tfstate-<ACCOUNT>
cp terraform.tfvars.example terraform.tfvars   # set sns_email

# 3. Deploy
cd ..
make deploy        # builds the Lambda zip, then terraform init + apply
# or: bash scripts/build_lambda.sh && terraform -chdir=terraform init -backend-config=backend.hcl && terraform -chdir=terraform apply
```

Confirm the SNS subscription email that arrives, then test:

```bash
BUCKET=$(terraform -chdir=terraform output -raw input_bucket)
aws s3 cp test/sample-image.jpg s3://$BUCKET/uploads/sample-image.jpg
# watch it run:
aws logs tail /aws/lambda/cloudsight-intake-processor --follow
```

> For a quick throwaway run without remote state, delete `terraform/backend.tf`
> and run `terraform init` with local state.

## Run the Streamlit app locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt
make app        # exports the terraform outputs and runs streamlit
```

## Enable Rekognition

```hcl
# terraform.tfvars
use_rekognition = true
```
`make deploy` again. Stays free for the first 12 months / 5,000 images per month.

---

## Viewing live X-Ray traces

The Lambda has `tracing_config { mode = "Active" }` and the handler calls
`aws_xray_sdk.core.patch_all()`, so S3 / DynamoDB / SNS / Rekognition calls show
as subsegments.

1. `terraform -chdir=terraform output xray_service_map_url` — open it. After an
   upload you'll see `AWS::Lambda` fanning out to DynamoDB, S3, SNS (and
   Rekognition when enabled), with latency and error rates on each edge.
2. `terraform -chdir=terraform output xray_traces_url` — the trace list. Click a
   trace for the waterfall timeline of one image.
3. CLI:
   ```bash
   aws xray get-trace-summaries \
     --start-time $(date -u -d '-15 min' +%s) --end-time $(date -u +%s) \
     --query 'TraceSummaries[].Id'
   ```
4. Disable locally / in tests with `AWS_XRAY_SDK_ENABLED=false` (CI sets this).

The CloudWatch dashboard (`terraform -chdir=terraform output dashboard_url`) shows
Lambda invocations/errors/throttles, duration avg + p99, DynamoDB consumed
capacity, and DLQ backlog.

---

## Development

```bash
pip install -r lambda/requirements.txt -r requirements-dev.txt
make lint      # ruff
make test      # pytest + moto (handler: metadata path, idempotency, skips, head_object fallback)
make fmt       # terraform fmt
```

CI (`.github/workflows/deploy.yml`): **test** job runs ruff + pytest + `terraform
fmt/validate` on every push and PR; **deploy** job runs `terraform apply` on push
to `main`.

Required repo **Secrets**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_REGION`, `SNS_EMAIL`. Optional repo **Variable**: `USE_REKOGNITION`.
Commit `terraform/backend.hcl` is git-ignored — either commit a non-secret copy
or add a CI step to render it from secrets.

## Teardown

```bash
BUCKET=$(terraform -chdir=terraform output -raw input_bucket)
OUT=$(terraform -chdir=terraform output -raw output_bucket)
aws s3 rm s3://$BUCKET --recursive ; aws s3 rm s3://$OUT --recursive
make destroy
```

---

# Push to GitHub & deploy the Streamlit app for a live public URL

### 1. Push this repo to GitHub

```bash
# from the repo root
git add -A
git commit -m "CloudSight Intake: serverless image pipeline"

# create the remote (GitHub CLI)
gh repo create cloudsight-intake --public --source=. --remote=origin --push
# …or, without gh: make an empty repo on github.com, then:
#   git remote add origin https://github.com/<you>/cloudsight-intake.git
#   git branch -M main
#   git push -u origin main
```

Confirm `.gitignore` did its job — none of these should be staged:
`terraform/backend.hcl`, `terraform/terraform.tfvars`, `terraform/*.tfstate*`,
`.streamlit/secrets.toml`, `terraform/build/`, `terraform/dist/`.

### 2. Deploy the AWS backend once (so the app has something to talk to)

Follow **Quickstart** above (or push to `main` with the four repo Secrets set and
let the `deploy` workflow run). Note the outputs:

```bash
terraform -chdir=terraform output   # input_bucket, output_bucket, dynamodb_table
```

### 3. Create a scoped IAM user for the app

The Streamlit app only needs to put objects, query one table, and get results:

```bash
aws iam create-user --user-name cloudsight-streamlit
aws iam put-user-policy --user-name cloudsight-streamlit \
  --policy-name cloudsight-streamlit \
  --policy-document '{
    "Version":"2012-10-17",
    "Statement":[
      {"Effect":"Allow","Action":"s3:PutObject","Resource":"arn:aws:s3:::cloudsight-intake-input-<ACCOUNT>/uploads/*"},
      {"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::cloudsight-intake-output-<ACCOUNT>/results/*"},
      {"Effect":"Allow","Action":["dynamodb:Query"],"Resource":"arn:aws:dynamodb:*:<ACCOUNT>:table/cloudsight-intake-results"}
    ]}'
aws iam create-access-key --user-name cloudsight-streamlit
```

### 4. Deploy to Streamlit Community Cloud

1. Go to <https://share.streamlit.io> and sign in with GitHub. Authorize access
   to the `cloudsight-intake` repo.
2. **Create app → Deploy a public app from GitHub**:
   - Repository: `<you>/cloudsight-intake`
   - Branch: `main`
   - **Main file path: `app/app.py`**
3. Open **Advanced settings → Python version → 3.11**.
   (Streamlit Cloud installs `app/requirements.txt` automatically.)
4. Paste into **Secrets** (TOML — see `.streamlit/secrets.toml.example`):
   ```toml
   AWS_REGION            = "us-east-1"
   AWS_ACCESS_KEY_ID     = "<from step 3>"
   AWS_SECRET_ACCESS_KEY = "<from step 3>"
   INPUT_BUCKET   = "cloudsight-intake-input-<ACCOUNT>"
   OUTPUT_BUCKET  = "cloudsight-intake-output-<ACCOUNT>"
   DYNAMODB_TABLE = "cloudsight-intake-results"
   ```
5. **Deploy**. You get a public URL like
   `https://cloudsight-intake-<hash>.streamlit.app` — share it for testing.
   Every push to `main` redeploys it automatically.

> Keep `use_rekognition = false` for a public demo so anonymous uploads can't run
> up Rekognition usage. The 7-day input-bucket purge cleans up whatever visitors
> upload.
