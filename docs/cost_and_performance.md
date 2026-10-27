# Cost and performance

BigQuery on-demand pricing charges for bytes scanned, so the shape of the tables and
of the dashboard queries decides the bill. The approach here:

## Tables

| Technique | Where | Effect |
|---|---|---|
| Day partitioning on `report_date` | every raw table, both facts, the `rpt_` daily tables | A query for last 30 days reads 30 partitions, not the whole history |
| Clustering | raw: account, campaign · facts: client, platform, campaign · rpt: client, channel | Filters on one client read a fraction of each partition |
| Pre-aggregated `rpt_` tables | `rpt_client_channel_daily` (date × client × channel) | Dashboards query thousands of rows, not campaign- or session-level data |
| Incremental facts | `fct_paid_media_daily`, `fct_web_traffic_daily` | Each run rewrites only the last 30 days' partitions (`insert_overwrite`) |
| Partition-decorator loads | raw layer (`table$20261026`, WRITE_TRUNCATE) | Load jobs are free; no DML bytes billed for replacing a day |

## Guardrails

- `maximum_bytes_billed: 10 GB` in the dbt BigQuery profile — a model that
  accidentally cross-joins fails instead of billing.
- 5 GB cap on every query the Python pipeline runs (quality checks).
- `job_execution_timeout_seconds` and `job_retries` set in the profile.
- Optional and worth it at scale: `require_partition_filter=true` on the fact tables
  so nobody — including a Data Studio chart without a date range — can scan the
  full history. (Then dbt tests on those models need a `where` config.)

## Dashboards

- Data sources use the partition column as the date range dimension → pruning.
- Data Studio caches results (12-hour freshness here); identical queries from
  different viewers reuse the cache.
- No custom-SQL data sources by default; they're harder to cache and to reason about.
- For heavy shared reports: BigQuery BI Engine on the `analytics` dataset.

## Monitoring

[`infra/bigquery/cost_monitoring.sql`](../infra/bigquery/cost_monitoring.sql) answers:

1. How much did we scan per day and per user/service account?
2. Which 20 queries cost the most this month? (Usually a chart pointing at a fact
   table, or missing a date filter.)
3. Which queries against the fact tables scanned > 1 GiB — i.e. where is partition
   pruning not happening?

## Rough numbers for scale

The demo's three clients produce ~50 raw rows a day; a real agency with 50
clients, ~2,000 active campaigns and GA4 at source/medium/campaign grain produces
in the order of 100k raw rows a day — a few GB a year. With partitioning and the
`rpt_` tables, daily dbt runs and dashboard traffic for that volume sit comfortably
inside BigQuery's free monthly query allowance on most setups. The guardrails exist
for the day someone points a chart at the wrong table.
