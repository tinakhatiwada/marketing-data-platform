{#- e.g. clicks can never exceed impressions; conversions-without-spend etc. -#}
{% test not_greater_than(model, column_name, compare_to) %}
select {{ column_name }}, {{ compare_to }}
from {{ model }}
where {{ column_name }} > {{ compare_to }}
{% endtest %}
