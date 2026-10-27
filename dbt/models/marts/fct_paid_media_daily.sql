{%- set inc = incremental_by_date_config() -%}
{{
    config(
        materialized='incremental',
        incremental_strategy=inc.incremental_strategy,
        unique_key=inc.unique_key,
        partition_by=date_partition(),
        cluster_by=clustering(['client_code', 'platform', 'campaign_id']),
        on_schema_change='append_new_columns'
    )
}}

-- Grain: one row per report_date × platform × campaign.
-- Only additive measures are stored. Ratios (CTR, CPC, CPA, ROAS) are defined as
-- SUM(numerator) / SUM(denominator) in the reporting layer — averaging a stored
-- daily ratio is the classic way dashboards end up confidently wrong.
--
-- Incremental: each run rebuilds the last `lookback_days` days (whole partitions),
-- because ad platforms keep restating conversions for weeks after the click.

select
    report_date,
    client_code,
    platform,
    account_id,
    campaign_id,
    campaign_name,
    campaign_type,
    objective,
    currency_code,
    impressions,
    clicks,
    spend_local,
    conversions,
    conversion_value_local,
    rate_to_aud,
    spend_aud,
    conversion_value_aud,
    {{ dbt.current_timestamp() }} as _model_updated_at

from {{ ref('int_paid_media__unioned') }}

{% if is_incremental() %}
where report_date >= {{ lookback_start_date() }}
{% endif %}
