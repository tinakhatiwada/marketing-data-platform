-- One row per (platform, campaign) with its latest name, parsed into attributes.
--
-- House naming convention:  {CLIENT}_{MARKET}_{OBJECTIVE}_{Descriptor}
--   e.g.  TWO_AU_CONV_Search-Brand
-- The *client* always comes from the ad account mapping (the source of truth);
-- the name supplies objective and market, and a mismatch between the two is
-- surfaced by a test rather than silently trusted.

with campaign_days as (

    select platform, account_id, campaign_id, campaign_name, report_date
    from {{ ref('stg_google_ads__campaign_daily') }}

    union all

    select platform, account_id, campaign_id, campaign_name, report_date
    from {{ ref('stg_meta_ads__campaign_daily') }}

),

latest as (

    select
        platform,
        account_id,
        campaign_id,
        campaign_name,
        min(report_date) over (partition by platform, campaign_id) as first_active_date,
        max(report_date) over (partition by platform, campaign_id) as last_active_date
    from campaign_days
    where 1 = 1
    qualify row_number() over (
        partition by platform, campaign_id
        order by report_date desc
    ) = 1

),

parsed as (

    select
        *,
        {{ regex_match('campaign_name',
                       "'^[A-Z]{3}_[A-Z]{2}_(CONV|LEAD|AWARE|TRAFFIC)_[A-Za-z0-9-]+$'") }}
            as follows_naming_convention
    from latest

)

select
    platform,
    account_id,
    campaign_id,
    campaign_name,
    follows_naming_convention,
    case when follows_naming_convention
         then {{ dbt.split_part('campaign_name', "'_'", 1) }} end   as name_client_code,
    case when follows_naming_convention
         then {{ dbt.split_part('campaign_name', "'_'", 2) }} end   as name_market,
    case
        when not follows_naming_convention then 'unknown'
        else case {{ dbt.split_part('campaign_name', "'_'", 3) }}
            when 'CONV'    then 'conversion'
            when 'LEAD'    then 'lead_generation'
            when 'AWARE'   then 'awareness'
            when 'TRAFFIC' then 'traffic'
        end
    end                                                              as objective,
    first_active_date,
    last_active_date

from parsed
