-- GA4 traffic with a channel assigned from the `channel_mapping` seed and the
-- client resolved from the GA4 property. The channel rules live in a seed so an
-- analyst can add "medium = paid_tiktok → paid_social" without touching SQL.

with traffic as (

    select * from {{ ref('stg_ga4__traffic_daily') }}

),

rules as (

    select * from {{ ref('channel_mapping') }}

),

matched as (

    select
        traffic.*,
        rules.channel
    from traffic
    inner join rules
        on  {{ regex_match('traffic.source', 'rules.source_pattern') }}
        and {{ regex_match('traffic.medium', 'rules.medium_pattern') }}
    where 1 = 1
    -- the catch-all rule (.*, .*) guarantees every row matches at least once
    qualify row_number() over (
        partition by traffic.report_date, traffic.property_id, traffic.source,
                     traffic.medium, traffic.campaign_name
        order by rules.priority
    ) = 1

),

fx as (

    select
        currency_code,
        rate_to_aud,
        valid_from,
        lead(valid_from) over (partition by currency_code order by valid_from) as valid_to
    from {{ ref('fx_rates') }}

)

select
    matched.report_date,
    clients.client_code,
    matched.property_id,
    matched.source,
    matched.medium,
    matched.campaign_name,
    matched.channel,
    matched.sessions,
    matched.engaged_sessions,
    matched.key_events,
    matched.currency_code,
    matched.revenue_local,
    matched.revenue_local * fx.rate_to_aud as revenue_aud

from matched
left join {{ ref('client_mapping') }} as clients
    on matched.property_id = clients.ga4_property_id
left join fx
    on  matched.currency_code = fx.currency_code
    and matched.report_date >= fx.valid_from
    and (fx.valid_to is null or matched.report_date < fx.valid_to)
