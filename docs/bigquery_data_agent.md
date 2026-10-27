# BigQuery data agent — making natural-language answers correct

BigQuery conversational agents (usable in BigQuery and shareable into Data Studio)
answer questions like *"What was Tidewater's paid social CPA last month?"* by
writing SQL against tables you choose. They are only as good as the model
underneath them. A model with ambiguous columns gets confident, wrong answers.

This project is shaped so the agent gets it right:

| What the agent needs | How the model provides it |
|---|---|
| Clear meaning for every column | dbt `persist_docs` writes the YAML descriptions onto every BigQuery table and column |
| Consistent names | `snake_case`, units in names (`spend_aud`, `spend_local`), the same name for the same thing in every table |
| Small, obvious tables | Point the agent at the three `rpt_` tables, not at raw or staging |
| No ambiguous ratios | Only additive measures are stored, so the agent must compute ratios from sums |
| One "conversions" meaning per column | `platform_conversions` vs `ga4_key_events`, never a blended column |

## Setup

1. In BigQuery, create a data agent with these knowledge sources:
   `analytics.rpt_client_channel_daily`, `analytics.rpt_campaign_performance_daily`,
   `analytics.rpt_budget_pacing`.
2. Paste the instructions below.
3. Add the verified queries as examples.
4. Share the agent to Data Studio for account teams.

## Agent instructions

```text
You answer questions about paid media and website performance for agency clients.

Tables
- rpt_client_channel_daily: one row per report_date × client × channel. Use for
  totals, channel mix, and anything combining spend with GA4 sessions/revenue.
- rpt_campaign_performance_daily: one row per report_date × platform × campaign.
  Use for campaign-level questions.
- rpt_budget_pacing: one row per client × month. Use for budget and pacing.

Rules
1. Always filter report_date to the period asked about. If no period is given,
   use the last 28 complete days and say so.
2. Compute every ratio as SUM(numerator) / SUM(denominator) over the whole period.
   Never average a ratio. CTR = SUM(clicks)/SUM(impressions);
   CPA = SUM(spend_aud)/SUM(platform_conversions);
   ROAS = SUM(platform_conversion_value_aud)/SUM(spend_aud).
3. Money is in AUD (spend_aud, *_aud). Say "AUD" in answers.
4. "Conversions" is ambiguous. Default to platform_conversions for paid-media
   questions and say so; use ga4_key_events when the user mentions GA4, the
   website or analytics. Never add the two together.
5. Clients are identified by client_name (e.g. "Tidewater Outdoors") or
   client_code (e.g. "TWO"). Match either.
6. Paid channels are channel IN ('paid_search', 'paid_social').
   Google Ads = paid_search, Meta / Facebook / Instagram = paid_social.
7. For lead-generation clients, call platform_conversions "leads" and CPA "CPL".
8. pacing_ratio is a status per client-month; never sum or average it.
9. If the data cannot answer the question, say so rather than guessing.
```

## Verified queries (examples to add to the agent)

```sql
-- "What was each client's CPA on paid social last month?"
SELECT
  client_name,
  SUM(spend_aud) AS spend_aud,
  SUM(platform_conversions) AS conversions,
  SAFE_DIVIDE(SUM(spend_aud), SUM(platform_conversions)) AS cpa_aud
FROM analytics.rpt_client_channel_daily
WHERE channel = 'paid_social'
  AND report_date BETWEEN DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH)
                      AND LAST_DAY(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH))
GROUP BY client_name
ORDER BY cpa_aud;

-- "Which 5 campaigns spent the most in the last 28 days, and what was their ROAS?"
SELECT
  client_name, platform, campaign_name,
  SUM(spend_aud) AS spend_aud,
  SAFE_DIVIDE(SUM(platform_conversion_value_aud), SUM(spend_aud)) AS roas_platform,
  SAFE_DIVIDE(SUM(ga4_revenue_aud), SUM(spend_aud)) AS roas_ga4
FROM analytics.rpt_campaign_performance_daily
WHERE report_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 28 DAY)
                      AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY 1, 2, 3
ORDER BY spend_aud DESC
LIMIT 5;

-- "Is anyone overspending this month?"
SELECT client_name, monthly_budget_aud, spend_mtd_aud, projected_spend_aud, pacing_status
FROM analytics.rpt_budget_pacing
WHERE month_start = DATE_TRUNC(CURRENT_DATE(), MONTH)
ORDER BY pacing_ratio DESC;
```

## Testing the agent

Before sharing it, ask it questions whose answers you know from the dashboard and
compare. The classic failures to test for: averaging CTR across campaigns,
summing platform conversions with GA4 key events, forgetting the date filter, and
mixing AUD and NZD. Each failure points to a description or instruction to tighten.
