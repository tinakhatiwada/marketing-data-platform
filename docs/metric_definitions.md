# Metric definitions

The single reference for what each number means. The same wording lives on the
BigQuery columns (via dbt `persist_docs`), so the definition a stakeholder reads
here is the one an analyst sees in the console and a data agent reads when
answering a question.

**Two rules that prevent most reporting mistakes**

1. **Ratios are computed from sums, never averaged.** `CTR = SUM(clicks) / SUM(impressions)`
   over whatever slice the chart shows. Averaging daily or per-campaign CTRs weights
   a 10-impression campaign the same as a 100,000-impression one.
2. **Platform results and GA4 results are different measurements.** They are shown
   side by side and never added together or substituted for each other.

## Base measures (stored)

| Field | Table(s) | Definition | Source | Aggregate with |
|---|---|---|---|---|
| `spend_aud` | fct_paid_media_daily, rpt_* | Media cost converted to AUD at the rate valid on `report_date` | Google `metrics.cost_micros / 1e6`; Meta `spend` | SUM |
| `spend_local` | fct_paid_media_daily | Media cost in the ad account's currency (`currency_code`) | as above | SUM *within one currency only* |
| `impressions` | fct_paid_media_daily, rpt_* | Times an ad was shown | Google `metrics.impressions`; Meta `impressions` | SUM |
| `clicks` | fct_paid_media_daily, rpt_* | Google: clicks. Meta: **link clicks** (`inline_link_clicks`) | — | SUM |
| `conversions` / `platform_conversions` | fct_paid_media_daily, rpt_* | Conversions as the ad platform reports them, using its own attribution model. Google values can be fractional (data-driven attribution). Meta: the first action type found in the priority list `omni_purchase → purchase → pixel purchase → lead → lead_grouped → pixel lead` | Google `metrics.conversions`; Meta `actions` | SUM |
| `conversion_value_aud` / `platform_conversion_value_aud` | fct_paid_media_daily, rpt_* | Value of those conversions in AUD | Google `metrics.conversions_value`; Meta `action_values` (same action type) | SUM |
| `ga4_sessions` / `sessions` | fct_web_traffic_daily, rpt_* | GA4 sessions | GA4 `sessions` | SUM |
| `ga4_engaged_sessions` | as above | Sessions lasting 10s+, with a key event, or 2+ page views | GA4 `engagedSessions` | SUM |
| `ga4_key_events` / `key_events` | as above | GA4 key events (renamed from "conversions" by Google in 2024), session-scoped last-click attribution | GA4 `keyEvents` | SUM |
| `ga4_revenue_aud` / `revenue_aud` | as above | GA4 total revenue converted to AUD | GA4 `totalRevenue` | SUM |
| `monthly_budget_aud` | rpt_budget_pacing | Agreed monthly media budget | `client_mapping` seed | Do not sum across months |

## Derived metrics (computed in Data Studio / queries)

| Metric | Formula | Notes |
|---|---|---|
| CTR | `SUM(clicks) / SUM(impressions)` | Comparable across platforms only because Meta uses link clicks |
| CPC | `SUM(spend_aud) / SUM(clicks)` | |
| CPM | `SUM(spend_aud) / SUM(impressions) * 1000` | |
| Conversion rate (platform) | `SUM(platform_conversions) / SUM(clicks)` | |
| CPA (platform) | `SUM(spend_aud) / SUM(platform_conversions)` | Call it CPL for lead-gen clients |
| ROAS (platform) | `SUM(platform_conversion_value_aud) / SUM(spend_aud)` | Platform-attributed; usually higher than GA4 ROAS |
| ROAS (GA4) | `SUM(ga4_revenue_aud) / SUM(spend_aud)` | Only meaningful on paid channels |
| Engagement rate | `SUM(ga4_engaged_sessions) / SUM(ga4_sessions)` | |
| Attribution gap | `SUM(ga4_key_events) / SUM(platform_conversions)` | Expect < 1 — see below |
| Projected month-end spend | `spend_mtd / days_elapsed × days_in_month` | Straight-line; stored in `rpt_budget_pacing` |
| Pacing ratio | `projected_spend / monthly_budget` | > 1.10 overpacing, < 0.90 underpacing. A per-row status — never average it |

## Dimensions

| Field | Definition |
|---|---|
| `report_date` | Day the activity happened, in the ad account / GA4 property timezone. The partition column — filter on it. |
| `client_code`, `client_name` | Resolved from the ad account or GA4 property via `client_mapping` (not from campaign names). |
| `platform` | `google_ads` or `meta_ads`. |
| `channel` | Medium-based grouping from the `channel_mapping` seed: `paid_search` (cpc/ppc), `paid_social` (paid/cpm), `organic_search`, `email`, `direct`, `referral`, `other`. All auto-tagged Google Ads traffic is `google / cpc`, so all Google Ads spend sits in `paid_search`. |
| `objective` | Parsed from the campaign name: `conversion`, `lead_generation`, `awareness`, `traffic`, or `unknown` when the name breaks the convention. |
| `campaign_type` | Google `advertising_channel_type` (search, performance_max, demand_gen…) or Meta objective (outcome_sales…). |
| `follows_naming_convention` | Name matches `{CLIENT}_{MARKET}_{OBJECTIVE}_{Descriptor}`, e.g. `TWO_AU_CONV_Search-Brand`. |

## Why platform conversions and GA4 key events don't match

This question comes up in every client meeting, so the answer is part of the model:

- **Attribution model.** Google Ads (often data-driven) and Meta (7-day click / 1-day
  view by default) credit conversions their own way; GA4 credits the session's source.
- **View-through.** Meta counts conversions after an ad *view*; GA4 can't see views.
- **Conversion date.** Platforms report against the *click* date, GA4 against the
  *conversion* date — which is also why the pipeline re-pulls 30 days daily.
- **Consent and blockers.** GA4 loses users who decline cookies or block scripts;
  platforms partly model them back in.

A stable gap is normal. A gap that suddenly changes is a tracking problem, and that's
what the `ga4_tracking` check and the Attribution gap chart are for.
