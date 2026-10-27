#!/usr/bin/env bash
# Creates the daily pacing-snapshot scheduled query (BigQuery Data Transfer Service).
# Scheduled-query times are UTC: 21:30 UTC ≈ 07:30–08:30 Sydney depending on DST,
# comfortably after the 06:17 pipeline run.
set -euo pipefail
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-australia-southeast1}"
QUERY="$(cat "$(dirname "$0")/pacing_snapshot.sql")"

bq mk --transfer_config \
  --project_id="$PROJECT_ID" \
  --location="$REGION" \
  --data_source=scheduled_query \
  --target_dataset=analytics \
  --display_name="adpulse: budget pacing snapshot" \
  --schedule="every day 21:30" \
  --params="$(jq -n --arg q "$QUERY" '{
      query: $q,
      destination_table_name_template: "budget_pacing_history",
      write_disposition: "WRITE_APPEND"
  }')"
