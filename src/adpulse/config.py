"""Runtime settings, read from environment variables (12-factor style).

Secrets (OAuth client secret, refresh token, Meta token, Slack webhook) are never
committed: locally they come from a `.env` file, in production from Secret Manager
mounted as environment variables on the Cloud Run job.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Repo root (holds dbt/ and .env). Set ADPULSE_HOME when the package is installed
# non-editable, e.g. in the Docker image.
PROJECT_ROOT = Path(os.getenv("ADPULSE_HOME", Path(__file__).resolve().parents[2]))


def _csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so the project has no extra dependency for it."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value[:1] in ('"', "'"):
            value = value[1:].split(value[0], 1)[0]
        else:
            value = value.split(" #", 1)[0].split("\t#", 1)[0].strip()
            if value.startswith("#"):
                value = ""
        os.environ.setdefault(key.strip(), value)


@dataclass
class Settings:
    # Where the data lands
    target: str = "local"  # "local" (DuckDB) or "bigquery"
    duckdb_path: Path = PROJECT_ROOT / "warehouse" / "adpulse.duckdb"
    gcp_project: str = ""
    bq_location: str = "australia-southeast1"
    raw_dataset: str = "raw"
    ops_dataset: str = "ops"
    analytics_dataset: str = "analytics"

    # Behaviour
    reporting_timezone: str = "Australia/Sydney"
    lookback_days: int = 30  # ad platforms restate conversions for ~28 days
    slack_webhook_url: str = ""

    # Google OAuth2 (shared by GA4 Data API and Google Ads API)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""

    # GA4
    ga4_property_ids: list[str] = field(default_factory=list)

    # Google Ads
    google_ads_developer_token: str = ""
    google_ads_login_customer_id: str = ""  # manager (MCC) account, digits only
    google_ads_customer_ids: list[str] = field(default_factory=list)
    google_ads_api_version: str = "v26"

    # Meta Marketing API
    meta_access_token: str = ""
    meta_app_secret: str = ""
    meta_ad_account_ids: list[str] = field(default_factory=list)
    meta_api_version: str = "v26.0"

    @classmethod
    def from_env(cls) -> Settings:
        _load_dotenv(PROJECT_ROOT / ".env")
        return cls(
            target=os.getenv("ADPULSE_TARGET", "local"),
            duckdb_path=Path(os.getenv("DUCKDB_PATH", str(cls.duckdb_path))).resolve(),
            gcp_project=os.getenv("GCP_PROJECT", ""),
            bq_location=os.getenv("BQ_LOCATION", cls.bq_location),
            raw_dataset=os.getenv("RAW_DATASET", cls.raw_dataset),
            ops_dataset=os.getenv("OPS_DATASET", cls.ops_dataset),
            analytics_dataset=os.getenv("ANALYTICS_DATASET", cls.analytics_dataset),
            reporting_timezone=os.getenv("REPORTING_TIMEZONE", cls.reporting_timezone),
            lookback_days=int(os.getenv("LOOKBACK_DAYS", cls.lookback_days)),
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
            google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            google_refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN", ""),
            ga4_property_ids=_csv("GA4_PROPERTY_IDS"),
            google_ads_developer_token=os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", ""),
            google_ads_login_customer_id=os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").replace(
                "-", ""
            ),
            google_ads_customer_ids=[c.replace("-", "") for c in _csv("GOOGLE_ADS_CUSTOMER_IDS")],
            google_ads_api_version=os.getenv("GOOGLE_ADS_API_VERSION", cls.google_ads_api_version),
            meta_access_token=os.getenv("META_ACCESS_TOKEN", ""),
            meta_app_secret=os.getenv("META_APP_SECRET", ""),
            meta_ad_account_ids=_csv("META_AD_ACCOUNT_IDS"),
            meta_api_version=os.getenv("META_API_VERSION", cls.meta_api_version),
        )

    # ---- date helpers -------------------------------------------------------------
    def today(self) -> date:
        """'Today' in the reporting timezone (clients are in AU/NZ, not UTC)."""
        return datetime.now(ZoneInfo(self.reporting_timezone)).date()

    def default_window(self) -> tuple[date, date]:
        """Re-pull the last N complete days to capture late-attributed conversions."""
        end = self.today() - timedelta(days=1)
        start = end - timedelta(days=self.lookback_days - 1)
        return start, end
