"""Read-only checks that the dashboard's numbers agree across reporting tables.

Run from the project root after the demo pipeline:
    python scripts/check_dashboard_data.py
"""

import os

import duckdb


def main() -> None:
    conn = duckdb.connect(os.getenv("DUCKDB_PATH", "warehouse/adpulse.duckdb"), read_only=True)

    queries = {
        "1. Channel types": """
            SELECT channel, is_paid_channel, COUNT(*) AS rows
            FROM analytics.rpt_client_channel_daily
            GROUP BY 1, 2
            ORDER BY 1, 2
        """,
        "2. Client coverage": """
            SELECT
                client_code,
                MIN(report_date) AS first_date,
                MAX(report_date) AS last_date,
                COUNT(*) AS rows,
                ROUND(SUM(spend_aud), 2) AS spend_aud,
                ROUND(SUM(ga4_revenue_aud), 2) AS ga4_revenue_aud
            FROM analytics.rpt_client_channel_daily
            GROUP BY client_code
            ORDER BY client_code
        """,
        "3. Campaign aggregation": """
            SELECT
                COUNT(*) AS rows,
                COUNT(DISTINCT campaign_id) AS campaigns,
                ROUND(SUM(spend_aud), 2) AS spend_aud,
                ROUND(SUM(ga4_revenue_aud), 2) AS ga4_revenue_aud,
                ROUND(SUM(ga4_sessions), 0) AS ga4_sessions
            FROM analytics.rpt_campaign_performance_daily
        """,
        # Paid channels only: campaign rows exist only for paid traffic, so organic, direct
        # and email revenue must not be compared with them (or used in GA4 ROAS).
        "4. Paid-channel GA4 totals vs campaign report, by client": """
            WITH channel_totals AS (
                SELECT
                    client_code,
                    SUM(ga4_revenue_aud) AS revenue,
                    SUM(ga4_sessions) AS sessions
                FROM analytics.rpt_client_channel_daily
                WHERE is_paid_channel
                GROUP BY client_code
            ),
            campaign_totals AS (
                SELECT
                    client_code,
                    SUM(ga4_revenue_aud) AS revenue,
                    SUM(ga4_sessions) AS sessions
                FROM analytics.rpt_campaign_performance_daily
                GROUP BY client_code
            )
            SELECT
                c.client_code,
                ROUND(c.revenue, 2) AS channel_revenue_aud,
                ROUND(p.revenue, 2) AS campaign_revenue_aud,
                c.sessions AS channel_sessions,
                p.sessions AS campaign_sessions
            FROM channel_totals AS c
            JOIN campaign_totals AS p USING (client_code)
            ORDER BY c.client_code
        """,
    }

    try:
        for title, sql in queries.items():
            print(f"\n{'=' * 65}\n{title}")
            print(conn.execute(sql).fetchdf().to_string(index=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
