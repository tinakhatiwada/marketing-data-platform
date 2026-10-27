"""Meta Marketing API connector (/act_{id}/insights).

Things that bite people with Meta data:
  * Throttling is reported as HTTP 400 (not 429) with error codes such as 4, 17,
    32, 613 or 80000-80014. We treat those as retryable.
  * Usage is reported in the `x-business-use-case-usage` header. When an account
    gets close to its limit we slow down *before* Meta starts rejecting calls.
  * "Clicks" includes likes, expands and profile clicks. `inline_link_clicks` is
    the field that is comparable to a Google Ads click, so dashboards use that.
  * Conversions live in an `actions` array where the same purchase can appear under
    several action types (omni_purchase, purchase, offsite_conversion.fb_pixel_purchase).
    Summing them double-counts, so we take the FIRST type found in a priority list
    (purchases first, then leads) and record which one we used.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date

import requests

from adpulse.auth import meta_appsecret_proof
from adpulse.connectors.base import Connector
from adpulse.http import HttpClient
from adpulse.schemas import META_ADS_CAMPAIGN_DAILY

log = logging.getLogger(__name__)

FIELDS = [
    "date_start", "account_id", "account_currency", "campaign_id", "campaign_name",
    "objective", "impressions", "clicks", "inline_link_clicks", "spend",
    "actions", "action_values",
]
CONVERSION_ACTION_PRIORITY = (
    "omni_purchase",
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
    "lead",
    "onsite_conversion.lead_grouped",
    "offsite_conversion.fb_pixel_lead",
)
THROTTLE_CODES = {4, 17, 32, 613} | set(range(80000, 80015))


def is_meta_throttle(resp: requests.Response) -> bool:
    try:
        code = resp.json().get("error", {}).get("code")
    except ValueError:
        return False
    return code in THROTTLE_CODES


def pick_action(actions: list[dict] | None, priority=CONVERSION_ACTION_PRIORITY):
    """Return (action_type, value) for the first action type present, else (None, 0.0)."""
    by_type = {a.get("action_type"): float(a.get("value", 0)) for a in (actions or [])}
    for action_type in priority:
        if action_type in by_type:
            return action_type, by_type[action_type]
    return None, 0.0


def max_business_usage(header: str | None) -> float:
    """Highest usage % across all businesses/metrics in x-business-use-case-usage."""
    if not header:
        return 0.0
    try:
        data = json.loads(header)
    except ValueError:
        return 0.0
    usage = 0.0
    for entries in data.values():
        for e in entries:
            usage = max(usage, *(float(e.get(k, 0)) for k in
                                 ("call_count", "total_cputime", "total_time")))
    return usage


class _UsageAwareSession(requests.Session):
    """Pauses when Meta reports we're close to the account's rate limit."""

    def __init__(self, threshold: float = 85.0, pause_s: float = 60.0, sleep=time.sleep):
        super().__init__()
        self.threshold, self.pause_s, self._sleep = threshold, pause_s, sleep

    def request(self, *args, **kwargs):
        resp = super().request(*args, **kwargs)
        usage = max_business_usage(resp.headers.get("x-business-use-case-usage"))
        if usage >= self.threshold:
            log.warning("meta usage high, pausing", extra={"context": {"usage_pct": usage}})
            self._sleep(self.pause_s)
        return resp


class MetaAdsConnector(Connector):
    name = "meta_ads"
    schema = META_ADS_CAMPAIGN_DAILY

    def __init__(self, ad_account_ids: list[str], access_token: str, app_secret: str = "",
                 api_version: str = "v26.0", http: HttpClient | None = None, **kw):
        super().__init__(**kw)
        if not ad_account_ids:
            raise ValueError("META_AD_ACCOUNT_IDS is empty")
        if not access_token:
            raise ValueError("META_ACCESS_TOKEN is missing")
        self.ad_account_ids = [a.removeprefix("act_") for a in ad_account_ids]
        self.access_token = access_token
        self.app_secret = app_secret
        self.base = f"https://graph.facebook.com/{api_version}"
        self.http = http or HttpClient(name="meta_ads", requests_per_minute=60,
                                       is_retryable=is_meta_throttle,
                                       session=_UsageAwareSession())

    def _auth_params(self) -> dict[str, str]:
        params = {"access_token": self.access_token}
        if self.app_secret:
            params["appsecret_proof"] = meta_appsecret_proof(self.access_token, self.app_secret)
        return params

    def fetch(self, start: date, end: date) -> list[dict]:
        rows: list[dict] = []
        for account_id in self.ad_account_ids:
            url: str | None = f"{self.base}/act_{account_id}/insights"
            params: dict | None = {
                **self._auth_params(),
                "level": "campaign",
                "time_increment": 1,
                "time_range": json.dumps({"since": start.isoformat(), "until": end.isoformat()}),
                "fields": ",".join(FIELDS),
                "limit": 500,
            }
            pages = 0
            while url:
                page = self.http.get(url, params=params)
                pages += 1
                for r in page.get("data", []):
                    action_type, conversions = pick_action(r.get("actions"))
                    _, conversion_value = pick_action(
                        r.get("action_values"), (action_type,) if action_type else ())
                    rows.append({
                        "report_date": r["date_start"],
                        "account_id": str(r.get("account_id", account_id)),
                        "campaign_id": str(r["campaign_id"]),
                        "campaign_name": r.get("campaign_name"),
                        "objective": r.get("objective"),
                        "currency_code": r.get("account_currency"),
                        "impressions": int(r.get("impressions", 0)),
                        "clicks_all": int(r.get("clicks", 0)),
                        "link_clicks": int(r.get("inline_link_clicks", 0)),
                        "spend": float(r.get("spend", 0)),
                        "conversions": conversions,
                        "conversion_value": conversion_value,
                        "conversion_action_type": action_type,
                        "actions_json": json.dumps(r.get("actions") or []),
                    })
                # `paging.next` is a complete URL (it already carries the token).
                url = page.get("paging", {}).get("next")
                params = None
            log.info("meta account extracted",
                     extra={"context": {"account_id": account_id, "pages": pages}})
        return rows
