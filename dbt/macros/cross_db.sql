{#
  Small cross-database helpers. The project runs on BigQuery in production and on
  DuckDB locally/in CI, so anything dialect-specific goes through adapter.dispatch.
#}

{# True when `expr` matches the RE2 regular expression `pattern` (a SQL expression). #}
{% macro regex_match(expr, pattern) -%}
    {{ return(adapter.dispatch('regex_match', 'adpulse')(expr, pattern)) }}
{%- endmacro %}

{% macro default__regex_match(expr, pattern) -%}
    regexp_matches({{ expr }}, {{ pattern }})
{%- endmacro %}

{% macro bigquery__regex_match(expr, pattern) -%}
    regexp_contains({{ expr }}, {{ pattern }})
{%- endmacro %}


{# First day of the month as a DATE. #}
{% macro month_start(date_expr) -%}
    cast({{ dbt.date_trunc('month', date_expr) }} as date)
{%- endmacro %}


{# Earliest report_date an incremental model rebuilds on this run. #}
{% macro lookback_start_date() -%}
    {%- set start = (modules.datetime.date.today()
                     - modules.datetime.timedelta(days=var('lookback_days'))) -%}
    date '{{ start.isoformat() }}'
{%- endmacro %}


{# Partition overwrite on BigQuery; per-date delete+insert elsewhere (same semantics). #}
{% macro incremental_by_date_config() -%}
    {%- if target.type == 'bigquery' -%}
        {{ return({'incremental_strategy': 'insert_overwrite', 'unique_key': none}) }}
    {%- else -%}
        {{ return({'incremental_strategy': 'delete+insert', 'unique_key': 'report_date'}) }}
    {%- endif -%}
{%- endmacro %}


{# BigQuery day partitioning on report_date; other adapters ignore it (returns none). #}
{% macro date_partition(field='report_date') -%}
    {%- if target.type == 'bigquery' -%}
        {{ return({'field': field, 'data_type': 'date', 'granularity': 'day'}) }}
    {%- else -%}
        {{ return(none) }}
    {%- endif -%}
{%- endmacro %}


{# BigQuery clustering; other adapters ignore it. #}
{% macro clustering(columns) -%}
    {{ return(columns if target.type == 'bigquery' else none) }}
{%- endmacro %}
