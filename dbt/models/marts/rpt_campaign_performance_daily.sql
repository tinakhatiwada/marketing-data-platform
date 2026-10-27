{{
    config(
        materialized='table',
        partition_by=date_partition(),
        cluster_by=clustering(['client_code', 'platform', 'campaign_name'])
    )
}}

-- Campaign drill-down: platform-reported results next to what GA4 saw for the
-- same campaign (matched on utm_campaign = campaign name). The gap between the
-- two is expected — platforms use their own attribution models, GA4 its own —
-- and putting them side by side is what lets an account team explain it.
-- Grain: report_date × platform × campaign.

with ga4_by_campaign as (

    select
        report_date,
        client_code,
        channel,
        lower(campaign_name)                as campaign_name_key,
        sum(sessions)                       as ga4_sessions,
        sum(engaged_sessions)               as ga4_engaged_sessions,
        sum(key_events)                     as ga4_key_events,
        sum(revenue_aud)                    as ga4_revenue_aud
    from {{ ref('fct_web_traffic_daily') }}
    where channel in ('paid_search', 'paid_social')
    group by 1, 2, 3, 4

)

select
    paid.report_date,
    paid.client_code,
    campaigns.client_name,
    campaigns.market,
    paid.platform,
    paid.campaign_id,
    paid.campaign_name,
    paid.campaign_type,
    paid.objective,
    campaigns.follows_naming_convention,
    paid.impressions,
    paid.clicks,
    paid.spend_aud,
    paid.conversions                        as platform_conversions,
    paid.conversion_value_aud               as platform_conversion_value_aud,
    coalesce(ga4.ga4_sessions, 0)           as ga4_sessions,
    coalesce(ga4.ga4_engaged_sessions, 0)   as ga4_engaged_sessions,
    coalesce(ga4.ga4_key_events, 0)         as ga4_key_events,
    coalesce(ga4.ga4_revenue_aud, 0)        as ga4_revenue_aud

from {{ ref('fct_paid_media_daily') }} as paid
left join {{ ref('dim_campaign') }} as campaigns
    on  paid.platform = campaigns.platform
    and paid.campaign_id = campaigns.campaign_id
left join ga4_by_campaign as ga4
    on  paid.report_date = ga4.report_date
    and paid.client_code = ga4.client_code
    and lower(paid.campaign_name) = ga4.campaign_name_key
    and ga4.channel = case paid.platform
                          when 'google_ads' then 'paid_search'
                          when 'meta_ads'   then 'paid_social'
                      end
