"""Deterministic synthetic data for three fictional agency clients.

Lets anyone clone the repo and run the full pipeline — extract, load, dbt, quality
checks — with no API credentials. The data is shaped like the real APIs' output
(same raw schemas), with realistic behaviour:

  * weekday/weekend patterns that differ by client (retail vs B2B lead gen),
  * different CPMs/CTRs/conversion rates per platform and campaign type,
  * GA4 reporting fewer conversions than the ad platforms (attribution gap),
  * an NZ client billed in NZD, so currency conversion is exercised,
  * one campaign that breaks the naming convention (so a dbt test flags it),
  * optional anomaly injection (a 4x budget-typo spend spike) to demo alerting.

Every value is seeded from (campaign, date), so re-pulling an overlapping range
returns identical numbers — exactly like an idempotent API backfill should.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

from adpulse.connectors.base import Connector
from adpulse.schemas import GA4_TRAFFIC_DAILY, GOOGLE_ADS_CAMPAIGN_DAILY, META_ADS_CAMPAIGN_DAILY


@dataclass(frozen=True)
class DemoClient:
    code: str
    currency: str
    ga4_property_id: str
    google_customer_id: str
    meta_account_id: str
    weekend_factor: float  # retail sells more at weekends, B2B less
    aov: float  # average order (or lead) value in local currency


@dataclass(frozen=True)
class DemoCampaign:
    client: str
    platform: str  # google_ads | meta_ads
    campaign_id: str
    name: str
    kind: str  # brand_search | generic_search | pmax | video | social_conv | social_aware ...
    daily_budget: float
    objective: str = ""


CLIENTS = {
    c.code: c
    for c in (
        DemoClient("TWO", "AUD", "310000001", "4110000001", "5220000001", 1.15, 145.0),
        DemoClient("BGE", "AUD", "310000002", "4110000002", "5220000002", 0.70, 60.0),
        DemoClient("KCR", "NZD", "310000003", "4110000003", "5220000003", 1.05, 52.0),
    )
}

CAMPAIGNS = (
    # Tidewater Outdoors — AU outdoor retailer
    DemoCampaign("TWO", "google_ads", "18001", "TWO_AU_CONV_Search-Brand", "brand_search", 180),
    DemoCampaign("TWO", "google_ads", "18002", "TWO_AU_CONV_Search-Generic", "generic_search", 420),
    DemoCampaign("TWO", "google_ads", "18003", "TWO_AU_CONV_PMax-Shopping", "pmax", 650),
    DemoCampaign("TWO", "google_ads", "18004", "TWO_AU_AWARE_YouTube-Summer", "video", 300),
    DemoCampaign("TWO", "meta_ads", "23850001", "TWO_AU_CONV_Advantage-Plus-Shopping",
                 "social_conv", 520, "OUTCOME_SALES"),
    DemoCampaign("TWO", "meta_ads", "23850002", "TWO_AU_AWARE_Reels-Summer",
                 "social_aware", 240, "OUTCOME_AWARENESS"),
    # Brightgrid Energy — AU solar, lead generation
    DemoCampaign("BGE", "google_ads", "18101", "BGE_AU_LEAD_Search-SolarQuotes", "generic_search",
                 380),
    DemoCampaign("BGE", "google_ads", "18102", "BGE_AU_LEAD_Search-Brand", "brand_search", 90),
    DemoCampaign("BGE", "google_ads", "18103", "BGE_AU_AWARE_Demand-Gen", "video", 160),
    DemoCampaign("BGE", "google_ads", "18199", "Test campaign - DO NOT USE", "generic_search", 6),
    DemoCampaign("BGE", "meta_ads", "23851001", "BGE_AU_LEAD_Lead-Forms-Solar", "social_lead",
                 300, "OUTCOME_LEADS"),
    DemoCampaign("BGE", "meta_ads", "23851002", "BGE_AU_TRAFFIC_Retargeting", "social_traffic",
                 110, "OUTCOME_TRAFFIC"),
    # Kereru Coffee Roasters — NZ coffee subscriptions, billed in NZD
    DemoCampaign("KCR", "google_ads", "18201", "KCR_NZ_CONV_Search-Brand", "brand_search", 70),
    DemoCampaign("KCR", "google_ads", "18202", "KCR_NZ_CONV_PMax-Subscriptions", "pmax", 210),
    DemoCampaign("KCR", "meta_ads", "23852001", "KCR_NZ_CONV_Subscriptions-Prospecting",
                 "social_conv", 260, "OUTCOME_SALES"),
)

# kind -> (cpm, ctr, conversion rate per click)
PROFILES = {
    "brand_search": (95.0, 0.180, 0.110),
    "generic_search": (60.0, 0.055, 0.035),
    "pmax": (14.0, 0.012, 0.030),
    "video": (9.0, 0.004, 0.004),
    "social_conv": (13.0, 0.011, 0.025),
    "social_aware": (6.0, 0.004, 0.003),
    "social_lead": (16.0, 0.013, 0.060),
    "social_traffic": (11.0, 0.017, 0.010),
}
GOOGLE_CHANNEL = {"brand_search": "SEARCH", "generic_search": "SEARCH",
                  "pmax": "PERFORMANCE_MAX", "video": "DEMAND_GEN"}

ANOMALY_CAMPAIGN = "23850001"  # TWO Advantage+ Shopping gets a budget-typo spike


def _rng(*key: object) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


class DemoWorld:
    def __init__(self, anomaly_date: date | None = None):
        self.anomaly_date = anomaly_date

    @lru_cache(maxsize=4096)  # noqa: B019 — small, per-process cache is intended
    def ads_day(self, d: date) -> tuple[tuple[DemoCampaign, dict], ...]:
        out = []
        for camp in CAMPAIGNS:
            client = CLIENTS[camp.client]
            rng = _rng(camp.campaign_id, d.isoformat())
            cpm, ctr, cvr = PROFILES[camp.kind]
            weekend = client.weekend_factor if d.weekday() >= 5 else 1.0
            # gentle upward trend through spring/summer + day-level noise
            trend = 1.0 + 0.002 * (d - date(2026, 1, 1)).days / 10
            spend = camp.daily_budget * weekend * trend * rng.lognormvariate(0, 0.12)
            if self.anomaly_date == d and camp.campaign_id == ANOMALY_CAMPAIGN:
                spend *= 4.0
            impressions = int(spend / cpm * 1000 * rng.lognormvariate(0, 0.08))
            clicks = min(impressions, int(impressions * ctr * rng.lognormvariate(0, 0.15)))
            conversions = clicks * cvr * rng.lognormvariate(0, 0.30)
            value = conversions * client.aov * rng.lognormvariate(0, 0.10)
            out.append((camp, {
                "spend": round(spend, 2), "impressions": impressions, "clicks": clicks,
                "conversions": conversions, "value": round(value, 2),
            }))
        return tuple(out)

    def google_rows(self, d: date) -> list[dict]:
        rows = []
        for camp, m in self.ads_day(d):
            if camp.platform != "google_ads":
                continue
            client = CLIENTS[camp.client]
            rows.append({
                "report_date": d,
                "customer_id": client.google_customer_id,
                "campaign_id": camp.campaign_id,
                "campaign_name": camp.name,
                "campaign_status": "ENABLED",
                "channel_type": GOOGLE_CHANNEL[camp.kind],
                "currency_code": client.currency,
                "impressions": m["impressions"],
                "clicks": m["clicks"],
                "cost_micros": int(round(m["spend"] * 1_000_000)),
                "conversions": round(m["conversions"], 2),  # data-driven attribution
                "conversions_value": m["value"],
            })
        return rows

    def meta_rows(self, d: date) -> list[dict]:
        rows = []
        for camp, m in self.ads_day(d):
            if camp.platform != "meta_ads":
                continue
            client = CLIENTS[camp.client]
            is_lead = camp.kind == "social_lead"
            conversions = float(round(m["conversions"]))
            action_type = "lead" if is_lead else "omni_purchase"
            rows.append({
                "report_date": d,
                "account_id": client.meta_account_id,
                "campaign_id": camp.campaign_id,
                "campaign_name": camp.name,
                "objective": camp.objective,
                "currency_code": client.currency,
                "impressions": m["impressions"],
                "clicks_all": int(m["clicks"] * 1.6),  # all clicks > link clicks
                "link_clicks": m["clicks"],
                "spend": m["spend"],
                "conversions": conversions,
                "conversion_value": m["value"] if conversions else 0.0,
                "conversion_action_type": action_type if conversions else None,
                "actions_json": "[]",
            })
        return rows

    def ga4_rows(self, d: date) -> list[dict]:
        rows = []
        for code, client in CLIENTS.items():
            rng = _rng("ga4", code, d.isoformat())

            def add(source, medium, campaign, sessions, key_events, revenue,
                    _client=client, _rng=rng):
                if sessions <= 0:
                    return
                rows.append({
                    "report_date": d,
                    "property_id": _client.ga4_property_id,
                    "session_source": source,
                    "session_medium": medium,
                    "session_campaign_name": campaign,
                    "sessions": int(sessions),
                    "engaged_sessions": int(sessions * _rng.uniform(0.52, 0.68)),
                    "key_events": round(key_events, 0),
                    "total_revenue": round(revenue, 2),
                    "currency_code": _client.currency,
                })

            for camp, m in self.ads_day(d):
                if camp.client != code:
                    continue
                if camp.platform == "google_ads":
                    # GA4 (last click) credits paid search less than Google's DDA does.
                    add("google", "cpc", camp.name, m["clicks"] * rng.uniform(0.82, 0.92),
                        m["conversions"] * 0.72, m["value"] * 0.75)
                else:
                    share_fb = rng.uniform(0.55, 0.65)
                    for src, share in (("facebook", share_fb), ("instagram", 1 - share_fb)):
                        add(src, "paid", camp.name, m["clicks"] * 0.70 * share,
                            m["conversions"] * 0.45 * share, m["value"] * 0.45 * share)

            weekend = client.weekend_factor if d.weekday() >= 5 else 1.0
            base = {"TWO": 2400, "BGE": 900, "KCR": 650}[code] * weekend
            cr = 0.018 if code != "BGE" else 0.025
            for source, medium, campaign, share in (
                ("google", "organic", "(organic)", 0.48),
                ("(direct)", "(none)", "(direct)", 0.30),
                ("newsletter", "email", "monthly-newsletter", 0.12),
                ("partner-site.example", "referral", "(referral)", 0.10),
            ):
                sessions = base * share * rng.lognormvariate(0, 0.10)
                key_events = sessions * cr * rng.lognormvariate(0, 0.2)
                add(source, medium, campaign, sessions, key_events, key_events * client.aov)
        return rows


def _dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


class _DemoConnector(Connector):
    def __init__(self, world: DemoWorld, **kw):
        super().__init__(**kw)
        self.world = world

    def _rows_for(self, d: date) -> list[dict]:  # pragma: no cover - overridden
        raise NotImplementedError

    def fetch(self, start: date, end: date) -> list[dict]:
        return [row for d in _dates(start, end) for row in self._rows_for(d)]


class DemoGA4Connector(_DemoConnector):
    name, schema = "ga4", GA4_TRAFFIC_DAILY

    def _rows_for(self, d):
        return self.world.ga4_rows(d)


class DemoGoogleAdsConnector(_DemoConnector):
    name, schema = "google_ads", GOOGLE_ADS_CAMPAIGN_DAILY

    def _rows_for(self, d):
        return self.world.google_rows(d)


class DemoMetaAdsConnector(_DemoConnector):
    name, schema = "meta_ads", META_ADS_CAMPAIGN_DAILY

    def _rows_for(self, d):
        return self.world.meta_rows(d)
