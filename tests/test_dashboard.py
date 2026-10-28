"""Smoke test: every dashboard page renders against a freshly built demo warehouse,
and headline numbers agree across pages."""

import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
pytest.importorskip("plotly")

from adpulse.config import Settings  # noqa: E402
from adpulse.pipeline import RunOptions, run  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app.py"
pytestmark = [pytest.mark.e2e,
              pytest.mark.skipif(shutil.which("dbt") is None, reason="dbt not installed")]


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    db = tmp_path_factory.mktemp("dash") / "adpulse.duckdb"
    end = date.today() - timedelta(days=1)
    settings = Settings(duckdb_path=db, lookback_days=30)
    assert run(settings, RunOptions(mode="demo", start=end - timedelta(days=44), end=end)) == 0
    os.environ["DUCKDB_PATH"] = str(db)
    yield db
    os.environ.pop("DUCKDB_PATH", None)


def open_page(page):
    at = st_testing.AppTest.from_file(str(APP), default_timeout=60).run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    return at


@pytest.mark.parametrize("page", ["Overview", "Campaigns", "Budget pacing", "Pipeline health"])
def test_page_renders(warehouse, page):
    at = open_page(page)
    assert len(at.sidebar.date_input) == 1          # one shared reporting period
    assert at.metric


def test_ga4_roas_agrees_between_overview_and_campaigns(warehouse):
    overview = {m.label: m.value for m in open_page("Overview").metric}
    campaigns = {m.label: m.value for m in open_page("Campaigns").metric}
    assert overview["GA4 ROAS (paid)"] == campaigns["GA4 ROAS"]
    # Overview abbreviates spend (A$115.4k); compare against the full figure in its tooltip.
    spend_help = next(m for m in open_page("Overview").metric if m.label == "Media spend").help
    assert campaigns["Campaign spend"] in spend_help
