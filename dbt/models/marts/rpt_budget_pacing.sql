-- Month-to-date spend vs. monthly budget per client, with a straight-line
-- projection to month end. Account managers check this daily; it's the table
-- that stops a client being over-spent by the 20th.
-- Grain: client × month. `pacing_ratio` is a per-row status, never aggregate it.

with monthly as (

    select
        client_code,
        {{ month_start('report_date') }}        as month_start,
        sum(spend_aud)                          as spend_mtd_aud,
        max(report_date)                        as data_through_date
    from {{ ref('fct_paid_media_daily') }}
    group by 1, 2

),

calc as (

    select
        monthly.client_code,
        clients.client_name,
        monthly.month_start,
        monthly.data_through_date,
        clients.monthly_budget_aud,
        monthly.spend_mtd_aud,
        extract(day from monthly.data_through_date)         as days_elapsed,
        extract(day from last_day(monthly.month_start))     as days_in_month
    from monthly
    left join {{ ref('client_mapping') }} as clients
        on monthly.client_code = clients.client_code

)

select
    client_code,
    client_name,
    month_start,
    data_through_date,
    monthly_budget_aud,
    spend_mtd_aud,
    days_elapsed,
    days_in_month,
    spend_mtd_aud / days_elapsed * days_in_month                       as projected_spend_aud,
    (spend_mtd_aud / days_elapsed * days_in_month) / monthly_budget_aud as pacing_ratio,
    case
        when (spend_mtd_aud / days_elapsed * days_in_month) / monthly_budget_aud > 1.10
            then 'overpacing'
        when (spend_mtd_aud / days_elapsed * days_in_month) / monthly_budget_aud < 0.90
            then 'underpacing'
        else 'on_track'
    end                                                                 as pacing_status

from calc
