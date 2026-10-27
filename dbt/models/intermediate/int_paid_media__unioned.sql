-- Google Ads + Meta in one shape, mapped to clients, converted to AUD.

with paid as (

    select
        report_date, platform, account_id, campaign_id, campaign_name, campaign_type,
        currency_code, impressions, clicks, spend_local, conversions, conversion_value_local
    from {{ ref('stg_google_ads__campaign_daily') }}

    union all

    select
        report_date, platform, account_id, campaign_id, campaign_name, campaign_type,
        currency_code, impressions, clicks, spend_local, conversions, conversion_value_local
    from {{ ref('stg_meta_ads__campaign_daily') }}

),

account_to_client as (

    select 'google_ads' as platform, google_ads_customer_id as account_id, client_code
    from {{ ref('client_mapping') }}

    union all

    select 'meta_ads' as platform, meta_ad_account_id as account_id, client_code
    from {{ ref('client_mapping') }}

),

fx as (

    -- Turn point-in-time rates into [valid_from, valid_to) ranges for a range join.
    select
        currency_code,
        rate_to_aud,
        valid_from,
        lead(valid_from) over (partition by currency_code order by valid_from) as valid_to
    from {{ ref('fx_rates') }}

)

select
    paid.report_date,
    paid.platform,
    paid.account_id,
    paid.campaign_id,
    paid.campaign_name,
    paid.campaign_type,
    account_to_client.client_code,
    campaigns.objective,
    campaigns.follows_naming_convention,
    paid.currency_code,
    paid.impressions,
    paid.clicks,
    paid.spend_local,
    paid.conversions,
    paid.conversion_value_local,
    fx.rate_to_aud,
    paid.spend_local * fx.rate_to_aud                   as spend_aud,
    paid.conversion_value_local * fx.rate_to_aud        as conversion_value_aud

from paid
left join account_to_client
    on  paid.platform = account_to_client.platform
    and paid.account_id = account_to_client.account_id
left join {{ ref('int_campaigns__parsed') }} as campaigns
    on  paid.platform = campaigns.platform
    and paid.campaign_id = campaigns.campaign_id
left join fx
    on  paid.currency_code = fx.currency_code
    and paid.report_date >= fx.valid_from
    and (fx.valid_to is null or paid.report_date < fx.valid_to)
