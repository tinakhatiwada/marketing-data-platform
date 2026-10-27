from datetime import date, timedelta

import pandas as pd
import pytest

from adpulse.config import Settings
from adpulse.connectors.demo import DemoGoogleAdsConnector, DemoMetaAdsConnector, DemoWorld
from adpulse.quality import FAIL, PASS, WARN, CheckResult, format_alert
from adpulse.schemas import GOOGLE_ADS_CAMPAIGN_DAILY
from adpulse.warehouse.duckdb_warehouse import DuckDBWarehouse

END = date(2026, 10, 26)


@pytest.fixture
def wh(tmp_path):
    w = DuckDBWarehouse(Settings(duckdb_path=tmp_path / "t.duckdb"))
    yield w
    w.close()


def test_demo_data_is_deterministic_across_overlapping_ranges():
    a = DemoGoogleAdsConnector(DemoWorld()).extract(END - timedelta(days=9), END)
    b = DemoGoogleAdsConnector(DemoWorld()).extract(END - timedelta(days=2), END)
    cols = ["report_date", "campaign_id", "cost_micros", "clicks"]
    tail = a[a["report_date"] >= END - timedelta(days=2)][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(tail, b[cols].reset_index(drop=True))


def test_anomaly_injection_only_hits_the_last_day():
    normal = DemoMetaAdsConnector(DemoWorld()).extract(END - timedelta(days=1), END)
    spiked = DemoMetaAdsConnector(DemoWorld(anomaly_date=END)).extract(
        END - timedelta(days=1), END)
    diff = spiked["spend"] / normal["spend"]
    assert sorted(diff.round(2).tolist()).count(1.0) == len(diff) - 1
    assert diff.max() == pytest.approx(4.0, rel=0.01)


def test_load_is_idempotent(wh):
    start = END - timedelta(days=4)
    df = DemoGoogleAdsConnector(DemoWorld()).extract(start, END)
    wh.replace_date_range("raw", GOOGLE_ADS_CAMPAIGN_DAILY, df, start, END)
    wh.replace_date_range("raw", GOOGLE_ADS_CAMPAIGN_DAILY, df, start, END)
    n = wh.query("select count(*) as n from raw.google_ads_campaign_daily")["n"].iloc[0]
    assert n == len(df)


def test_empty_extract_never_wipes_existing_days(wh):
    start = END - timedelta(days=2)
    df = DemoGoogleAdsConnector(DemoWorld()).extract(start, END)
    wh.replace_date_range("raw", GOOGLE_ADS_CAMPAIGN_DAILY, df, start, END)

    # API returns nothing for the last day (outage) — earlier load must survive.
    partial = df[df["report_date"] < END]
    wh.replace_date_range("raw", GOOGLE_ADS_CAMPAIGN_DAILY, partial, start, END)
    days = wh.query("select count(distinct report_date) as d "
                    "from raw.google_ads_campaign_daily")["d"].iloc[0]
    assert days == 3


def test_alert_lists_failures_first_and_skips_when_clean():
    results = [
        CheckResult("volume", "meta", WARN, "low"),
        CheckResult("freshness", "ga4", FAIL, "2 days behind"),
        CheckResult("reconciliation", "rpt", PASS, "ok"),
    ]
    text = format_alert(results, "run1")
    lines = text.splitlines()
    assert "1 failing, 1 warning" in lines[0]
    assert "freshness" in lines[1] and "volume" in lines[2]
    assert "reconciliation" not in text
    assert format_alert([CheckResult("x", "y", PASS, "fine")], "r") is None
