"""GA4 Data API connector (properties.runReport).

We pull from the Data API rather than the GA4 → BigQuery export because agencies
often don't own the client's GA4 property and can't switch on the export. The
trade-off: the Data API applies thresholding/sampling on some reports and caps
rows per request, so we paginate with offset/limit and log the quota we have left.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from adpulse.auth import GoogleOAuth2
from adpulse.connectors.base import Connector
from adpulse.http import HttpClient
from adpulse.schemas import GA4_TRAFFIC_DAILY

log = logging.getLogger(__name__)

API = "https://analyticsdata.googleapis.com/v1beta"
DIMENSIONS = ["date", "sessionSource", "sessionMedium", "sessionCampaignName"]
METRICS = ["sessions", "engagedSessions", "keyEvents", "totalRevenue"]


class GA4Connector(Connector):
    name = "ga4"
    schema = GA4_TRAFFIC_DAILY

    def __init__(self, property_ids: list[str], auth: GoogleOAuth2,
                 http: HttpClient | None = None, page_size: int = 100_000, **kw):
        super().__init__(**kw)
        if not property_ids:
            raise ValueError("GA4_PROPERTY_IDS is empty")
        self.property_ids = property_ids
        self.auth = auth
        self.page_size = page_size
        # GA4 core quota is token-based; ~60 rpm keeps us comfortably inside it.
        self.http = http or HttpClient(name="ga4", requests_per_minute=60)

    def _report_page(self, property_id: str, start: date, end: date, offset: int) -> dict:
        body = {
            "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
            "dimensions": [{"name": d} for d in DIMENSIONS],
            "metrics": [{"name": m} for m in METRICS],
            "limit": self.page_size,
            "offset": offset,
            "keepEmptyRows": False,
            "returnPropertyQuota": True,
        }
        return self.http.post(f"{API}/properties/{property_id}:runReport",
                              json=body, headers=self.auth.headers())

    def fetch(self, start: date, end: date) -> list[dict]:
        rows: list[dict] = []
        for property_id in self.property_ids:
            offset, total = 0, None
            while total is None or offset < total:
                page = self._report_page(property_id, start, end, offset)
                total = int(page.get("rowCount", 0))
                currency = page.get("metadata", {}).get("currencyCode")
                page_rows = page.get("rows", [])
                for r in page_rows:
                    dims = [d.get("value") for d in r["dimensionValues"]]
                    mets = [m.get("value") for m in r["metricValues"]]
                    rows.append({
                        "report_date": datetime.strptime(dims[0], "%Y%m%d").date(),
                        "property_id": property_id,
                        "session_source": dims[1],
                        "session_medium": dims[2],
                        "session_campaign_name": dims[3],
                        "sessions": int(mets[0] or 0),
                        "engaged_sessions": int(mets[1] or 0),
                        "key_events": float(mets[2] or 0),
                        "total_revenue": float(mets[3] or 0),
                        "currency_code": currency,
                    })
                if not page_rows:
                    break
                offset += len(page_rows)

            quota = page.get("propertyQuota", {}).get("tokensPerDay", {})
            log.info("ga4 property extracted", extra={"context": {
                "property_id": property_id, "rows": total,
                "tokens_per_day_remaining": quota.get("remaining")}})
        return rows
