{{
    config(
        materialized='table',
        partition_by=date_partition(),
        cluster_by=clustering(['client_code', 'channel'])
    )
}}

-- The executive-overview table behind the Data Studio report.
-- Grain: report_date × client × channel. Small, pre-aggregated and partitioned, so
-- a dashboard filtered to "last 30 days, one client" scans kilobytes, not the
-- full campaign-level history.
--
-- Channel follows GA4's medium-based grouping: all auto-tagged Google Ads traffic
-- arrives as google / cpc → paid_search; Meta arrives as facebook|instagram / paid
-- → paid_social. That's what lets spend and sessions sit on the same row.

with paid as (

    select
        report_date,
        client_code,
        case platform
            when 'google_ads' then 'paid_search'
            when 'meta_ads'   then 'paid_social'
        end                                 as channel,
        sum(spend_aud)                      as spend_aud,
        sum(impressions)                    as impressions,
        sum(clicks)                         as clicks,
        sum(conversions)                    as platform_conversions,
        sum(conversion_value_aud)           as platform_conversion_value_aud
    from {{ ref('fct_paid_media_daily') }}
    group by 1, 2, 3

),

web as (

    select
        report_date,
        client_code,
        channel,
        sum(sessions)                       as ga4_sessions,
        sum(engaged_sessions)               as ga4_engaged_sessions,
        sum(key_events)                     as ga4_key_events,
        sum(revenue_aud)                    as ga4_revenue_aud
    from {{ ref('fct_web_traffic_daily') }}
    group by 1, 2, 3

),

joined as (

    select
        coalesce(paid.report_date, web.report_date)     as report_date,
        coalesce(paid.client_code, web.client_code)     as client_code,
        coalesce(paid.channel, web.channel)             as channel,
        coalesce(paid.spend_aud, 0)                     as spend_aud,
        coalesce(paid.impressions, 0)                   as impressions,
        coalesce(paid.clicks, 0)                        as clicks,
        coalesce(paid.platform_conversions, 0)          as platform_conversions,
        coalesce(paid.platform_conversion_value_aud, 0) as platform_conversion_value_aud,
        coalesce(web.ga4_sessions, 0)                   as ga4_sessions,
        coalesce(web.ga4_engaged_sessions, 0)           as ga4_engaged_sessions,
        coalesce(web.ga4_key_events, 0)                 as ga4_key_events,
        coalesce(web.ga4_revenue_aud, 0)                as ga4_revenue_aud
    from paid
    full outer join web
        on  paid.report_date = web.report_date
        and paid.client_code = web.client_code
        and paid.channel = web.channel

)

select
    joined.report_date,
    joined.client_code,
    clients.client_name,
    clients.market,
    joined.channel,
    joined.channel in ('paid_search', 'paid_social')   as is_paid_channel,
    joined.spend_aud,
    joined.impressions,
    joined.clicks,
    joined.platform_conversions,
    joined.platform_conversion_value_aud,
    joined.ga4_sessions,
    joined.ga4_engaged_sessions,
    joined.ga4_key_events,
    joined.ga4_revenue_aud

from joined
left join {{ ref('client_mapping') }} as clients
    on joined.client_code = clients.client_code
