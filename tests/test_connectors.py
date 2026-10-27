import json
from datetime import date

import pytest

from adpulse.auth import GoogleOAuth2
from adpulse.connectors.ga4 import GA4Connector
from adpulse.connectors.google_ads import GoogleAdsConnector
from adpulse.connectors.meta_ads import MetaAdsConnector, max_business_usage, pick_action
from adpulse.http import HttpClient
from adpulse.schemas import SchemaError
from tests.conftest import FakeAuth, FakeResponse, FakeSession

D1, D2 = date(2026, 10, 1), date(2026, 10, 2)


def http(session, sleep=lambda s: None, **kw):
    return HttpClient(name="t", session=session, sleep=sleep, **kw)


# ---------------------------------------------------------------- Google Ads --

def ads_row(campaign_id, day, cost_micros="2500000"):
    return {
        "customer": {"id": "123", "currencyCode": "AUD"},
        "campaign": {"id": campaign_id, "name": f"C{campaign_id}", "status": "ENABLED",
                     "advertisingChannelType": "SEARCH"},
        "segments": {"date": day},
        "metrics": {"impressions": "100", "clicks": "7", "costMicros": cost_micros,
                    "conversions": 1.5, "conversionsValue": 90.0},
    }


def test_google_ads_paginates_and_parses():
    session = FakeSession([
        FakeResponse(200, {"results": [ads_row("1", "2026-10-01")], "nextPageToken": "p2"}),
        FakeResponse(200, {"results": [ads_row("2", "2026-10-02")]}),
    ])
    conn = GoogleAdsConnector(["123"], "dev-token", FakeAuth(), login_customer_id="999",
                              http=http(session), run_id="r1")
    df = conn.extract(D1, D2)

    assert len(df) == 2
    assert df["cost_micros"].tolist() == [2_500_000, 2_500_000]
    assert df["impressions"].dtype.name == "Int64"  # strings coerced to ints
    assert session.calls[1]["json"]["pageToken"] == "p2"
    headers = session.calls[0]["headers"]
    assert headers["developer-token"] == "dev-token"
    assert headers["login-customer-id"] == "999"
    assert "BETWEEN '2026-10-01' AND '2026-10-02'" in session.calls[0]["json"]["query"]
    assert set(df["_run_id"]) == {"r1"}


def test_google_ads_requires_developer_token():
    with pytest.raises(ValueError):
        GoogleAdsConnector(["123"], "", FakeAuth())


# ----------------------------------------------------------------------- Meta --

def meta_row(campaign_id, day, actions=None, values=None):
    return {
        "date_start": day, "account_id": "555", "account_currency": "AUD",
        "campaign_id": campaign_id, "campaign_name": f"M{campaign_id}",
        "objective": "OUTCOME_SALES", "impressions": "1000", "clicks": "40",
        "inline_link_clicks": "25", "spend": "12.34",
        "actions": actions, "action_values": values,
    }


def test_meta_follows_paging_next_and_counts_one_purchase_type():
    actions = [{"action_type": "purchase", "value": "3"},
               {"action_type": "omni_purchase", "value": "3"},
               {"action_type": "link_click", "value": "25"}]
    values = [{"action_type": "purchase", "value": "300"},
              {"action_type": "omni_purchase", "value": "300"}]
    session = FakeSession([
        FakeResponse(200, {"data": [meta_row("1", "2026-10-01", actions, values)],
                           "paging": {"next": "https://graph.facebook.com/next-page"}}),
        FakeResponse(200, {"data": [meta_row("2", "2026-10-02")]}),
    ])
    conn = MetaAdsConnector(["act_555"], "tok", http=http(session))
    df = conn.extract(D1, D2)

    first = df.iloc[0]
    assert first["conversions"] == 3  # not 6 — no double counting across action types
    assert first["conversion_value"] == 300
    assert first["conversion_action_type"] == "omni_purchase"
    assert first["link_clicks"] == 25 and first["clicks_all"] == 40
    assert df.iloc[1]["conversions"] == 0
    assert session.calls[1]["url"] == "https://graph.facebook.com/next-page"
    assert session.calls[1]["params"] is None  # next URL already carries everything
    assert json.loads(session.calls[0]["params"]["time_range"]) == {
        "since": "2026-10-01", "until": "2026-10-02"}


def test_meta_throttle_error_is_retried():
    from adpulse.connectors.meta_ads import is_meta_throttle

    session = FakeSession([
        FakeResponse(400, {"error": {"code": 17, "message": "User request limit reached"}}),
        FakeResponse(200, {"data": []}),
    ])
    conn = MetaAdsConnector(["555"], "tok", http=http(session, is_retryable=is_meta_throttle))
    assert conn.extract(D1, D1).empty
    assert len(session.calls) == 2


def test_pick_action_falls_back_to_leads():
    assert pick_action([{"action_type": "lead", "value": "4"}]) == ("lead", 4.0)
    assert pick_action(None) == (None, 0.0)


def test_business_usage_header():
    header = json.dumps({"555": [{"call_count": 12, "total_cputime": 91, "total_time": 3}]})
    assert max_business_usage(header) == 91
    assert max_business_usage(None) == 0


# ------------------------------------------------------------------------ GA4 --

def ga4_page(rows, total):
    return {
        "rowCount": total,
        "metadata": {"currencyCode": "AUD"},
        "rows": [{"dimensionValues": [{"value": d} for d in r[:4]],
                  "metricValues": [{"value": m} for m in r[4:]]} for r in rows],
    }


def test_ga4_offset_pagination():
    session = FakeSession([
        FakeResponse(200, ga4_page([["20261001", "google", "cpc", "c1", "10", "6", "1", "50.5"]],
                                   2)),
        FakeResponse(200, ga4_page([["20261002", "(direct)", "(none)", "(direct)", "4", "2", "0",
                                     "0"]], 2)),
    ])
    conn = GA4Connector(["42"], FakeAuth(), http=http(session), page_size=1)
    df = conn.extract(D1, D2)

    assert df["report_date"].tolist() == [D1, D2]
    assert df["sessions"].tolist() == [10, 4]
    assert [c["json"]["offset"] for c in session.calls] == [0, 1]
    assert df["currency_code"].unique().tolist() == ["AUD"]


# ----------------------------------------------------------------------- auth --

def test_google_oauth_caches_until_near_expiry():
    now = [1000.0]
    session = FakeSession([
        FakeResponse(200, {"access_token": "a1", "expires_in": 3600}),
        FakeResponse(200, {"access_token": "a2", "expires_in": 3600}),
    ])
    auth = GoogleOAuth2("id", "secret", "refresh", http=http(session), clock=lambda: now[0])
    assert auth.access_token() == "a1"
    now[0] += 3000
    assert auth.access_token() == "a1"  # still valid
    now[0] += 560  # within 60s of expiry → refresh
    assert auth.access_token() == "a2"
    assert session.calls[0]["data"]["grant_type"] == "refresh_token"


def test_google_oauth_reports_missing_settings():
    with pytest.raises(ValueError, match="GOOGLE_REFRESH_TOKEN"):
        GoogleOAuth2("id", "secret", "")


# -------------------------------------------------------------------- schemas --

def test_unexpected_api_field_fails_loudly():
    class Broken(GoogleAdsConnector):
        def fetch(self, start, end):
            return [{**self_row, "surprise_field": 1}]

    self_row = {"report_date": "2026-10-01", "customer_id": "1", "campaign_id": "2",
                "campaign_name": "x", "campaign_status": "ENABLED", "channel_type": "SEARCH",
                "currency_code": "AUD", "impressions": 1, "clicks": 0, "cost_micros": 0,
                "conversions": 0.0, "conversions_value": 0.0}
    with pytest.raises(SchemaError, match="surprise_field"):
        Broken(["1"], "t", FakeAuth()).extract(D1, D1)
