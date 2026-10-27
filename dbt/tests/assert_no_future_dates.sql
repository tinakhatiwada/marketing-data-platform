-- Data dated in the future means a timezone bug or a bad API response.
-- (+1 day of tolerance: Sydney is ahead of the UTC servers that run the job.)

select 'fct_paid_media_daily' as model, report_date
from {{ ref('fct_paid_media_daily') }}
where report_date > cast({{ dbt.dateadd('day', 1, 'current_date') }} as date)

union all

select 'fct_web_traffic_daily' as model, report_date
from {{ ref('fct_web_traffic_daily') }}
where report_date > cast({{ dbt.dateadd('day', 1, 'current_date') }} as date)
