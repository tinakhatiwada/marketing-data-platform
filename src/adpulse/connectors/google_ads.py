"""Google Ads API connector (REST, GAQL via googleAds:search).

Notes worth knowing:
  * Requires a developer token AND OAuth2. When accounts sit under a manager (MCC)
    account, `login-customer-id` must be the manager's id.
  * int64 fields (impressions, cost_micros, ids) arrive as JSON *strings*.
  * Money is in micros: 1,000,000 cost_micros = 1 unit of account currency.
    We keep micros in raw and convert in dbt staging, so raw stays lossless.
  * Paginate via nextPageToken until it's absent.
"""

from __future__ import annotations

import logging
from datetime import date

from adpulse.auth import GoogleOAuth2
from adpulse.connectors.base import Connector
from adpulse.http import HttpClient
from adpulse.schemas import GOOGLE_ADS_CAMPAIGN_DAILY

log = logging.getLogger(__name__)

GAQL = """
SELECT
  customer.id,
  customer.currency_code,
  campaign.id,
  campaign.name,
  campaign.status,
  campaign.advertising_channel_type,
  segments.date,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value
FROM campaign
WHERE segments.date BETWEEN '{start}' AND '{end}'
  AND metrics.impressions > 0
"""


class GoogleAdsConnector(Connector):
    name = "google_ads"
    schema = GOOGLE_ADS_CAMPAIGN_DAILY

    def __init__(self, customer_ids: list[str], developer_token: str, auth: GoogleOAuth2,
                 login_customer_id: str = "", api_version: str = "v26",
                 http: HttpClient | None = None, **kw):
        super().__init__(**kw)
        if not customer_ids:
            raise ValueError("GOOGLE_ADS_CUSTOMER_IDS is empty")
        if not developer_token:
            raise ValueError("GOOGLE_ADS_DEVELOPER_TOKEN is missing")
        self.customer_ids = customer_ids
        self.developer_token = developer_token
        self.login_customer_id = login_customer_id
        self.auth = auth
        self.base = f"https://googleads.googleapis.com/{api_version}"
        self.http = http or HttpClient(name="google_ads", requests_per_minute=120)

    def _headers(self) -> dict[str, str]:
        headers = {**self.auth.headers(), "developer-token": self.developer_token}
        if self.login_customer_id:
            headers["login-customer-id"] = self.login_customer_id
        return headers

    def fetch(self, start: date, end: date) -> list[dict]:
        query = GAQL.format(start=start.isoformat(), end=end.isoformat())
        rows: list[dict] = []
        for customer_id in self.customer_ids:
            url = f"{self.base}/customers/{customer_id}/googleAds:search"
            page_token, pages = None, 0
            while True:
                body = {"query": query}
                if page_token:
                    body["pageToken"] = page_token
                page = self.http.post(url, json=body, headers=self._headers())
                pages += 1
                for r in page.get("results", []):
                    c, m, s = r.get("campaign", {}), r.get("metrics", {}), r.get("segments", {})
                    rows.append({
                        "report_date": s["date"],
                        "customer_id": str(r.get("customer", {}).get("id", customer_id)),
                        "campaign_id": str(c["id"]),
                        "campaign_name": c.get("name"),
                        "campaign_status": c.get("status"),
                        "channel_type": c.get("advertisingChannelType"),
                        "currency_code": r.get("customer", {}).get("currencyCode"),
                        "impressions": int(m.get("impressions", 0)),
                        "clicks": int(m.get("clicks", 0)),
                        "cost_micros": int(m.get("costMicros", 0)),
                        "conversions": float(m.get("conversions", 0)),
                        "conversions_value": float(m.get("conversionsValue", 0)),
                    })
                page_token = page.get("nextPageToken")
                if not page_token:
                    break
            log.info("google ads customer extracted",
                     extra={"context": {"customer_id": customer_id, "pages": pages}})
        return rows
