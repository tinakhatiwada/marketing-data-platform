{%- set inc = incremental_by_date_config() -%}
{{
    config(
        materialized='incremental',
        incremental_strategy=inc.incremental_strategy,
        unique_key=inc.unique_key,
        partition_by=date_partition(),
        cluster_by=clustering(['client_code', 'channel']),
        on_schema_change='append_new_columns'
    )
}}

-- Grain: one row per report_date × GA4 property × source × medium × campaign.

select
    report_date,
    client_code,
    property_id,
    channel,
    source,
    medium,
    campaign_name,
    sessions,
    engaged_sessions,
    key_events,
    currency_code,
    revenue_local,
    revenue_aud,
    {{ dbt.current_timestamp() }} as _model_updated_at

from {{ ref('int_ga4__traffic_channelled') }}

{% if is_incremental() %}
where report_date >= {{ lookback_start_date() }}
{% endif %}
