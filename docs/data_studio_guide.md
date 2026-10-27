# Data Studio build guide

How to build the client reporting dashboard on top of the `analytics` and `ops`
datasets. (Google renamed Looker Studio back to **Data Studio** in April 2026;
older docs and the connector gallery may still use the Looker Studio name.)

## 0. Get data into BigQuery

Real accounts: `adpulse run --target bigquery --days 90`.
Or with the demo data, which is ideal for building and screenshotting the report:

```bash
gcloud auth application-default login
export GCP_PROJECT=your-project
adpulse run --mode demo --target bigquery --days 90 --full-refresh
```

> **BigQuery sandbox note:** the free sandbox has no DML, so incremental dbt runs
> (which use `MERGE`) fail there. Pass `--full-refresh` on every run in the sandbox;
> on a billing-enabled project, run normally.

## 1. Data sources

Create one data source per reporting table — **not** one custom-SQL source per
chart. Fewer sources means a better cache hit rate and one place to define fields.

| Data source | BigQuery table | Date range dimension |
|---|---|---|
| `AdPulse · Client channel daily` | `analytics.rpt_client_channel_daily` | `report_date` |
| `AdPulse · Campaign daily` | `analytics.rpt_campaign_performance_daily` | `report_date` |
| `AdPulse · Budget pacing` | `analytics.rpt_budget_pacing` | `month_start` |
| `AdPulse · Pipeline health` | `ops.data_quality_results` | `checked_date` |

For each: *Add data → BigQuery → project → dataset → table*. Then in the data source:

- Set the **date range dimension** to the partition column above. Data Studio then
  sends the report's date range as a filter on that column, so BigQuery prunes
  partitions — a 30-day view of one client scans a few kilobytes.
- Set **data freshness** to 12 hours (the pipeline runs once a day).
- Set `spend_aud`, `ga4_revenue_aud` etc. to **Currency (AUD)**; `client_code`,
  `channel`, `platform` to Text; turn **off** default aggregation for ratio fields.
- Field descriptions are already filled in from the BigQuery column descriptions.

## 2. Calculated fields

Add these to the data source (not per chart), so every chart uses the same formula.
Each divides sums — see [metric definitions](metric_definitions.md) for why.

```text
CTR                 SUM(clicks) / SUM(impressions)
CPC                 SUM(spend_aud) / SUM(clicks)
CPM                 SUM(spend_aud) / SUM(impressions) * 1000
CPA (platform)      SUM(spend_aud) / SUM(platform_conversions)
ROAS (platform)     SUM(platform_conversion_value_aud) / SUM(spend_aud)
ROAS (GA4)          SUM(ga4_revenue_aud) / SUM(spend_aud)
Engagement rate     SUM(ga4_engaged_sessions) / SUM(ga4_sessions)
Attribution gap     SUM(ga4_key_events) / SUM(platform_conversions)
Channel label       CASE channel
                      WHEN "paid_search" THEN "Paid search"
                      WHEN "paid_social" THEN "Paid social"
                      WHEN "organic_search" THEN "Organic search"
                      ELSE CONCAT(UPPER(SUBSTR(channel, 1, 1)), SUBSTR(channel, 2, 100))
                    END
```

Format CTR, Engagement rate and Attribution gap as percent; CPC/CPA as currency;
ROAS as a number with 2 decimals (or "x" suffix).

Pipeline health source:

```text
Status order        CASE status WHEN "fail" THEN 1 WHEN "warn" THEN 2 ELSE 3 END
Is problem          status IN ("fail", "warn")
```

## 3. Pages

Report-level controls (top of every page): **date range** (default: last 28 days,
compare to previous period) and a **client** drop-down on `client_name`.

### Page 1 — Overview (`Client channel daily`)
- Scorecards: Spend, Platform conversions, CPA (platform), ROAS (GA4), GA4 sessions —
  each with comparison to previous period.
- Time series: Spend (bars) and Platform conversions (line), by day.
- Table by `Channel label`: Spend, Clicks, CTR, CPA, GA4 sessions, GA4 key events,
  Engagement rate. Heatmap on CPA.
- Stacked bar: GA4 sessions by channel by week — shows paid vs organic mix.

### Page 2 — Campaigns (`Campaign daily`)
- Filter controls: platform, objective.
- Table by campaign: Spend, Impressions, CTR, CPC, Platform conversions, GA4 key events,
  Attribution gap, ROAS (platform), ROAS (GA4). Sort by Spend.
- Scatter: Spend (x) vs CPA (y), bubble per campaign — finds expensive campaigns fast.
- A small table filtered to `follows_naming_convention = false` titled
  "Campaigns breaking the naming convention".

### Page 3 — Budget pacing (`Budget pacing`)
- Filter: `month_start` = current month (or date control on `month_start`).
- Bullet chart per client: `spend_mtd_aud` vs `monthly_budget_aud`, with
  `projected_spend_aud` as the target marker.
- Table: client, budget, MTD spend, projected, pacing ratio, `pacing_status`
  with conditional colour (overpacing red, underpacing amber).
- Optional: with the scheduled query in `infra/bigquery/` creating
  `analytics.budget_pacing_history`, a line chart of pacing ratio by snapshot date.

### Page 4 — Pipeline health (`Pipeline health`)
- Scorecards: checks failed / warned in the last run.
- Table: checked_at, check_name, subject, status, message — sorted by Status order;
  conditional formatting on status.
- Time series: count of fail/warn by checked_date.

Account managers see at a glance whether today's numbers can be trusted.

## 4. Blending (when you need it)

The `rpt_` tables already join paid media and GA4, so most charts need no blend.
If you blend (e.g. pacing with daily spend), join on `client_code` and a date key,
and keep blends to two sources: blends are re-computed in Data Studio and are the
first thing to slow a report down.

## 5. Performance checklist

- Charts point at `rpt_` tables, not at `fct_` tables or raw data.
- Every data source has its date range dimension set to the partition column.
- No custom SQL data sources unless a chart truly needs one (they bypass caching
  and push the full query to BigQuery on every refresh).
- Keep it under ~10 charts per page; use drill-down instead of more charts.
- If many people use the report, consider BigQuery BI Engine on the `analytics`
  dataset, or Data Studio extract data sources for the heaviest pages.

## 6. Scheduled delivery (Data Studio Pro)

With Data Studio Pro the report lives in a team workspace (not one person's
account), and can be scheduled — e.g. the Overview page as a PDF to each client's
account manager every Monday 08:00, plus an alert when the Pipeline health page
shows a failure.

## 7. Conversational analytics

Data Studio can surface BigQuery data agents for natural-language questions.
See [bigquery_data_agent.md](bigquery_data_agent.md) for the agent setup — it
should be pointed at the same `rpt_` tables, with the same metric rules.

## Screenshots

Once built, add screenshots to `docs/img/` and link them from the README —
an overview page, the campaign table and the pipeline-health page are enough.
