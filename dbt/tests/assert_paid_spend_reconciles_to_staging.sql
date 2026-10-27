-- Spend must survive the transformations intact: for every platform and day in the
-- rebuild window, local-currency spend in the fact table equals staging to the cent.
-- A failure here means a join fanned out (duplicated rows) or dropped rows.

with staging as (

    select platform, report_date, sum(spend_local) as spend
    from (
        select platform, report_date, spend_local from {{ ref('stg_google_ads__campaign_daily') }}
        union all
        select platform, report_date, spend_local from {{ ref('stg_meta_ads__campaign_daily') }}
    ) as s
    where report_date >= {{ lookback_start_date() }}
    group by 1, 2

),

fact as (

    select platform, report_date, sum(spend_local) as spend
    from {{ ref('fct_paid_media_daily') }}
    where report_date >= {{ lookback_start_date() }}
    group by 1, 2

)

select
    coalesce(staging.platform, fact.platform)       as platform,
    coalesce(staging.report_date, fact.report_date) as report_date,
    staging.spend                                   as staging_spend,
    fact.spend                                      as fact_spend
from staging
full outer join fact
    on  staging.platform = fact.platform
    and staging.report_date = fact.report_date
where abs(coalesce(staging.spend, 0) - coalesce(fact.spend, 0)) > 0.01
