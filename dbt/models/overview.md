{% docs __overview__ %}
# AdPulse: model documentation

These pages document the dbt project behind **AdPulse**, a marketing data platform that
combines GA4, Google Ads and Meta Ads data for an agency's clients.
Source code, architecture and dashboard screenshots are on
[GitHub](https://github.com/tinakhatiwada/marketing-data-platform).

This site is rebuilt by CI on every push to `main`, from the local demo warehouse
(DuckDB, synthetic data for three fictional clients). The same models run on BigQuery
in production.

## How the models are layered

| Layer | Models | What happens there |
|---|---|---|
| **Sources** | `raw.*` | API responses loaded as-is, one table per source |
| **Staging** | `stg_*` | renamed, typed, cleaned; one model per source table |
| **Intermediate** | `int_*` | campaign-name parsing, GA4 channel grouping, Google + Meta unioned into one shape |
| **Marts** | `dim_*`, `fct_*` | conformed campaign dimension and daily facts, in AUD |
| **Reports** | `rpt_*` | what dashboards read: campaign performance, client × channel, budget pacing |

## Where to start

- **`rpt_campaign_performance_daily`**: one row per campaign per day, with spend,
  platform conversions and GA4 outcomes side by side.
- **`rpt_client_channel_daily`**: GA4 traffic and media spend by client and channel.
- **`rpt_budget_pacing`**: month-to-date spend against budget and projected month end.

Click the blue button at the bottom right to open the **lineage graph**.

## Rules every dashboard follows

- Ratios (CTR, CPC, CPA, ROAS) are computed as `SUM(numerator) / SUM(denominator)`,
  never as an average of daily ratios.
- GA4 ROAS uses revenue from **paid channels only**.
- NZD amounts are converted to AUD with the `fx_rates` seed.
- Platform-reported and GA4-attributed conversions are kept in separate columns,
  because they use different attribution and are not expected to match.

Every column is described on its model's page, and the tests on each model (uniqueness,
not-null, accepted values, spend reconciliation) are listed alongside it.
{% enddocs %}
