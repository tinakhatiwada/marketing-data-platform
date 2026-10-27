{#
  Use the configured schema (BigQuery dataset) name as-is — `staging`, `analytics`,
  `reference` — instead of dbt's default `<target_schema>_<custom_schema>`, so
  Data Studio data sources point at stable, readable dataset names.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
