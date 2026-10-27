-- GA4 sessions / key events / revenue by date × source × medium × campaign.

with source as (

    select * from {{ source('raw', 'ga4_traffic_daily') }}

),

deduplicated as (

    select *
    from source
    where 1 = 1
    qualify row_number() over (
        partition by report_date, property_id, session_source, session_medium,
                     session_campaign_name
        order by _extracted_at desc
    ) = 1

)

select
    report_date,
    property_id,
    lower(trim(session_source))         as source,
    lower(trim(session_medium))         as medium,
    trim(session_campaign_name)         as campaign_name,
    sessions,
    engaged_sessions,
    key_events,
    total_revenue                       as revenue_local,
    upper(currency_code)                as currency_code,
    _extracted_at

from deduplicated
