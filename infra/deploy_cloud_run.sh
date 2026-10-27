#!/usr/bin/env bash
# Deploys the pipeline as a Cloud Run job, triggered daily by Cloud Scheduler.
#
#   Cloud Scheduler (06:17 Sydney) ──► Cloud Run job ──► APIs → BigQuery → dbt → checks
#                                           │
#                                           └─ secrets from Secret Manager, logs to Cloud Logging
#
# Usage:  PROJECT_ID=my-project ./infra/deploy_cloud_run.sh
# Re-running is safe: every step is create-or-update.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-australia-southeast1}"
JOB="adpulse-pipeline"
REPO="adpulse"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/pipeline:$(git rev-parse --short HEAD 2>/dev/null || echo latest)"
RUNNER_SA="adpulse-runner@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA="adpulse-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"
SECRETS=(google-client-secret google-refresh-token google-ads-developer-token meta-access-token slack-webhook-url)

gcloud config set project "$PROJECT_ID" >/dev/null

echo "▸ Enabling APIs"
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com \
  bigquery.googleapis.com bigquerydatatransfer.googleapis.com

echo "▸ Artifact Registry"
gcloud artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 ||
  gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION"

echo "▸ Building image $IMAGE"
gcloud builds submit --tag "$IMAGE" .

echo "▸ Service accounts (least privilege)"
for sa in adpulse-runner adpulse-scheduler; do
  gcloud iam service-accounts describe "${sa}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$sa" --display-name "$sa"
done
# Runner: run query/load jobs and write tables. (Tighten dataEditor to the four
# datasets once they exist: raw, staging, analytics, ops.)
for role in roles/bigquery.jobUser roles/bigquery.dataEditor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --quiet \
    --member "serviceAccount:${RUNNER_SA}" --role "$role" >/dev/null
done

echo "▸ Secrets (values are added separately, never in this script)"
for s in "${SECRETS[@]}"; do
  name="adpulse-${s}"
  gcloud secrets describe "$name" >/dev/null 2>&1 || {
    gcloud secrets create "$name" --replication-policy automatic
    echo "  created $name — add a value with:"
    echo "  printf '%s' 'VALUE' | gcloud secrets versions add $name --data-file=-"
  }
  gcloud secrets add-iam-policy-binding "$name" --quiet \
    --member "serviceAccount:${RUNNER_SA}" --role roles/secretmanager.secretAccessor >/dev/null
done

echo "▸ Cloud Run job"
gcloud run jobs deploy "$JOB" \
  --image "$IMAGE" \
  --region "$REGION" \
  --service-account "$RUNNER_SA" \
  --tasks 1 --max-retries 1 --task-timeout 3600s \
  --memory 2Gi --cpu 1 \
  --set-env-vars "ADPULSE_TARGET=bigquery,GCP_PROJECT=${PROJECT_ID},BQ_LOCATION=${REGION},LOOKBACK_DAYS=30,REPORTING_TIMEZONE=Australia/Sydney" \
  --set-env-vars "GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:-},GA4_PROPERTY_IDS=${GA4_PROPERTY_IDS:-}" \
  --set-env-vars "GOOGLE_ADS_CUSTOMER_IDS=${GOOGLE_ADS_CUSTOMER_IDS:-},GOOGLE_ADS_LOGIN_CUSTOMER_ID=${GOOGLE_ADS_LOGIN_CUSTOMER_ID:-}" \
  --set-env-vars "META_AD_ACCOUNT_IDS=${META_AD_ACCOUNT_IDS:-}" \
  --set-secrets "GOOGLE_CLIENT_SECRET=adpulse-google-client-secret:latest,GOOGLE_REFRESH_TOKEN=adpulse-google-refresh-token:latest,GOOGLE_ADS_DEVELOPER_TOKEN=adpulse-google-ads-developer-token:latest,META_ACCESS_TOKEN=adpulse-meta-access-token:latest,SLACK_WEBHOOK_URL=adpulse-slack-webhook-url:latest"

echo "▸ Cloud Scheduler (daily 06:17 Australia/Sydney, after platforms finalise yesterday)"
gcloud run jobs add-iam-policy-binding "$JOB" --region "$REGION" --quiet \
  --member "serviceAccount:${SCHEDULER_SA}" --role roles/run.invoker >/dev/null
RUN_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB}:run"
if gcloud scheduler jobs describe adpulse-daily --location "$REGION" >/dev/null 2>&1; then
  ACTION=update
else
  ACTION=create
fi
gcloud scheduler jobs "$ACTION" http adpulse-daily \
  --location "$REGION" \
  --schedule "17 6 * * *" \
  --time-zone "Australia/Sydney" \
  --uri "$RUN_URI" \
  --http-method POST \
  --oauth-service-account-email "$SCHEDULER_SA"

echo "✔ Deployed. Run once now with:  gcloud run jobs execute $JOB --region $REGION --wait"
