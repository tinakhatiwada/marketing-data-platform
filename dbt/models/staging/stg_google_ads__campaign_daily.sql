-- Google Ads campaign performance, one row per campaign per day.
-- Staging only renames, casts and de-duplicates. No business logic lives here.

with source as (

    select * from {{ source('raw', 'google_ads_campaign_daily') }}

),

deduplicated as (

    -- If a day was ever loaded twice (e.g. a manual backfill racing the schedule),
    -- keep the most recent extract so spend can never be double-counted.
    select *
    from source
    where 1 = 1
    qualify row_number() over (
        partition by report_date, customer_id, campaign_id
        order by _extracted_at desc
    ) = 1

)

select
    report_date,
    'google_ads'                        as platform,
    customer_id                         as account_id,
    campaign_id,
    trim(campaign_name)                 as campaign_name,
    lower(campaign_status)              as campaign_status,
    lower(channel_type)                 as campaign_type,
    upper(currency_code)                as currency_code,
    impressions,
    clicks,
    cost_micros / 1000000.0             as spend_local,
    conversions,
    conversions_value                   as conversion_value_local,
    _extracted_at

from deduplicated
