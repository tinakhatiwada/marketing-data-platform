# Runbook

Where to look and what to do when something goes wrong. Every run writes its checks
to `ops.data_quality_results`; Slack gets the warn/fail summary; Cloud Logging has
the structured JSON logs (filter on `jsonPayload.run_id`).

## A check failed

| Check | Likely cause | What to do |
|---|---|---|
| `freshness` (1 day behind = warn, 2+ = fail) | Expired/revoked token, API outage, job didn't run | Check the Cloud Run execution logs. `401/403` → refresh the token (below). Then backfill the missing days. |
| `volume` | Partial extract (API returned some accounts, not others); an account was removed from a manager account | Compare rows per account for the day in `raw.*`. Re-run that source for the day. |
| `spend_anomaly` | Real: budget typo, campaign paused, billing hold. Data: duplicated or missing rows | Confirm in the ad platform UI first. If the platform shows the same number, it's real — tell the account team. If not, re-pull the day. |
| `ga4_tracking` | GA4 tag removed or broken in a site release; consent banner change | Check GA4 Realtime for the property. Tell the client's dev team with the date it started. |
| `reconciliation` | A model change fanned out a join | Run `dbt build -s rpt_client_channel_daily+` and inspect the failing dbt test output. |
| dbt `relationships` / `not_null` on `client_code` | A new ad account or GA4 property isn't in `client_mapping` | Add it to `dbt/seeds/client_mapping.csv` and deploy. |
| dbt warn: naming convention | Someone created a campaign with a free-text name | Send the list (Campaigns page) to the account team; it's a warning, nothing is blocked. |

## Backfills

Loads are idempotent, so a backfill is just a run with dates:

```bash
# one source, one month
adpulse run --target bigquery --sources meta_ads --start 2026-09-01 --end 2026-09-30

# raw only, then rebuild everything downstream from scratch
adpulse extract --target bigquery --start 2026-01-01 --end 2026-09-30
adpulse transform --target bigquery --full-refresh
```

In Cloud Run: `gcloud run jobs execute adpulse-pipeline --region australia-southeast1 --args="run,--json-logs,--start,2026-09-01,--end,2026-09-30" --wait`.

Large backfills: Google Ads and GA4 handle 90-day ranges in one go; for Meta, split
long ranges by month to avoid timeouts on big accounts.

## Tokens

| Token | Lifetime | Renew |
|---|---|---|
| Google refresh token | Until revoked (or 7 days if the OAuth app is in "Testing" — publish it) | `python scripts/get_google_refresh_token.py`, then `gcloud secrets versions add adpulse-google-refresh-token --data-file=-` |
| Google Ads developer token | Doesn't expire | — |
| Meta System User token | Non-expiring if created as such; revoked if the user loses access | Business Settings → System Users → Generate token (`ads_read`) |

## API version upgrades

Google Ads and Meta retire API versions on a schedule. Versions are pinned by
`GOOGLE_ADS_API_VERSION` and `META_API_VERSION`. To upgrade: read the release
notes for renamed fields, bump the env var in a branch, run a one-week backfill
into a scratch dataset (`RAW_DATASET=raw_upgrade_test`), compare totals, then
deploy. The schema contracts make field renames fail loudly at extract time.

## Adding a client

1. Grant the agency's Google account access to the GA4 property and Google Ads
   account; add the System User to the Meta ad account.
2. Add the IDs to the job's env vars (`GA4_PROPERTY_IDS`, `GOOGLE_ADS_CUSTOMER_IDS`,
   `META_AD_ACCOUNT_IDS`) and a row to `client_mapping.csv` with the monthly budget.
3. Backfill 90 days for the new accounts. The client appears in every dashboard
   automatically.
