-- Who and what is spending BigQuery money? Run monthly, or put it on a dashboard page.
-- (Adjust the region qualifier to wherever your datasets live.)

-- 1) Cost by day and principal, last 30 days (on-demand pricing; check your region's rate)
SELECT
  DATE(creation_time, 'Australia/Sydney')          AS day,
  user_email,
  COUNT(*)                                          AS queries,
  ROUND(SUM(total_bytes_billed) / POW(1024, 4), 3)  AS tib_billed
FROM `region-australia-southeast1`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND job_type = 'QUERY'
  AND state = 'DONE'
GROUP BY 1, 2
ORDER BY day DESC, tib_billed DESC;

-- 2) The 20 most expensive queries — usually a dashboard chart without a date filter,
--    or a query on a campaign-level table that should hit a pre-aggregated rpt_ table.
SELECT
  creation_time,
  user_email,
  ROUND(total_bytes_billed / POW(1024, 3), 2)       AS gib_billed,
  total_slot_ms,
  cache_hit,
  LEFT(query, 300)                                  AS query_start
FROM `region-australia-southeast1`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND job_type = 'QUERY'
ORDER BY total_bytes_billed DESC
LIMIT 20;

-- 3) Is partition pruning working? Queries on the fact tables that scanned > 1 GiB.
SELECT
  creation_time,
  user_email,
  ROUND(total_bytes_processed / POW(1024, 3), 2)    AS gib_processed,
  LEFT(query, 300)                                  AS query_start
FROM `region-australia-southeast1`.INFORMATION_SCHEMA.JOBS_BY_PROJECT,
  UNNEST(referenced_tables) AS t
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND t.table_id IN ('fct_paid_media_daily', 'fct_web_traffic_daily')
  AND total_bytes_processed > POW(1024, 3)
ORDER BY total_bytes_processed DESC;
