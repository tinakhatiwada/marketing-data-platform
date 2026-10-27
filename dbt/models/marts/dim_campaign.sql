-- One row per campaign (per platform) with client, objective and convention checks.

select
    campaigns.platform || '-' || campaigns.campaign_id      as campaign_key,
    campaigns.platform,
    campaigns.account_id,
    campaigns.campaign_id,
    campaigns.campaign_name,
    accounts.client_code,
    clients.client_name,
    coalesce(campaigns.name_market, clients.market)        as market,
    campaigns.objective,
    campaigns.follows_naming_convention,
    campaigns.name_client_code,
    campaigns.first_active_date,
    campaigns.last_active_date

from {{ ref('int_campaigns__parsed') }} as campaigns
left join (
    select 'google_ads' as platform, google_ads_customer_id as account_id, client_code
    from {{ ref('client_mapping') }}
    union all
    select 'meta_ads' as platform, meta_ad_account_id as account_id, client_code
    from {{ ref('client_mapping') }}
) as accounts
    on  campaigns.platform = accounts.platform
    and campaigns.account_id = accounts.account_id
left join {{ ref('client_mapping') }} as clients
    on accounts.client_code = clients.client_code
