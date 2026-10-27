"""End-to-end: demo extract → DuckDB → dbt build → quality checks.

Slower (~10s) because it runs dbt for real. Skip with `pytest -m "not e2e"`.
"""

import shutil
from datetime import date

import duckdb
import pytest

from adpulse.config import Settings
from adpulse.pipeline import RunOptions, run

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(shutil.which("dbt") is None, reason="dbt not installed"),
]

END = date.today()


def test_full_demo_pipeline(tmp_path):
    settings = Settings(duckdb_path=tmp_path / "e2e.duckdb", lookback_days=30)
    start = date.fromordinal(END.toordinal() - 44)

    assert run(settings, RunOptions(mode="demo", start=start, end=END)) == 0

    # Same window again with an injected spike: idempotent load + incremental dbt,
    # and the spend-anomaly check must fail the run.
    code = run(settings, RunOptions(mode="demo", start=start, end=END, inject_anomaly=True))
    assert code == 1

    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    n, days = con.execute(
        "select count(*), count(distinct report_date) from analytics.fct_paid_media_daily"
    ).fetchone()
    assert days == 45 and n == days * 15  # 15 campaigns, no duplicated days
    failed = con.execute(
        "select subject from ops.data_quality_results where status = 'fail'").fetchall()
    assert failed == [("TWO/meta_ads",)]
    con.close()
