-- BigQuery scheduled query: append today's budget-pacing rows to a history table.
--
-- dbt rebuilds `analytics.rpt_budget_pacing` as a *current-state* table. Account
-- teams also want to see how pacing moved through the month ("we were 15% over on
-- the 10th, back on track by the 20th"), so this scheduled query snapshots it daily
-- into `analytics.budget_pacing_history` (WRITE_APPEND, set in the transfer config).
--
-- Schedule it after the pipeline finishes — see create_scheduled_query.sh.

SELECT
  CURRENT_DATE('Australia/Sydney') AS snapshot_date,
  client_code,
  client_name,
  month_start,
  data_through_date,
  monthly_budget_aud,
  spend_mtd_aud,
  projected_spend_aud,
  pacing_ratio,
  pacing_status
FROM `analytics.rpt_budget_pacing`
WHERE month_start = DATE_TRUNC(CURRENT_DATE('Australia/Sydney'), MONTH)
