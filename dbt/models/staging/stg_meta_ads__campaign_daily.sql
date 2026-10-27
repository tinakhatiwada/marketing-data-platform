-- Meta campaign performance, one row per campaign per day.
-- `clicks` is deliberately Meta's *link* clicks: "all clicks" includes likes,
-- comments and photo expands, which would make Meta CTR/CPC incomparable with Google.

with source as (

    select * from {{ source('raw', 'meta_ads_campaign_daily') }}

),

deduplicated as (

    select *
    from source
    where 1 = 1
    qualify row_number() over (
        partition by report_date, account_id, campaign_id
        order by _extracted_at desc
    ) = 1

)

select
    report_date,
    'meta_ads'                          as platform,
    account_id,
    campaign_id,
    trim(campaign_name)                 as campaign_name,
    cast(null as {{ dbt.type_string() }}) as campaign_status,
    lower(objective)                    as campaign_type,
    upper(currency_code)                as currency_code,
    impressions,
    link_clicks                         as clicks,
    clicks_all,
    spend                               as spend_local,
    conversions,
    conversion_value                    as conversion_value_local,
    conversion_action_type,
    _extracted_at

from deduplicated
