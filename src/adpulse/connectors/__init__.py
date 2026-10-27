"""Source connectors and a factory that builds them from Settings."""

from __future__ import annotations

from datetime import date

from adpulse.auth import GoogleOAuth2
from adpulse.config import Settings
from adpulse.connectors.base import Connector
from adpulse.connectors.demo import (
    DemoGA4Connector,
    DemoGoogleAdsConnector,
    DemoMetaAdsConnector,
    DemoWorld,
)
from adpulse.connectors.ga4 import GA4Connector
from adpulse.connectors.google_ads import GoogleAdsConnector
from adpulse.connectors.meta_ads import MetaAdsConnector

SOURCES = ("ga4", "google_ads", "meta_ads")


def build_connectors(
    settings: Settings,
    *,
    mode: str,
    sources: tuple[str, ...] = SOURCES,
    run_id: str,
    anomaly_date: date | None = None,
) -> list[Connector]:
    if mode == "demo":
        world = DemoWorld(anomaly_date=anomaly_date)
        demo = {
            "ga4": DemoGA4Connector,
            "google_ads": DemoGoogleAdsConnector,
            "meta_ads": DemoMetaAdsConnector,
        }
        return [demo[s](world, run_id=run_id) for s in sources]

    connectors: list[Connector] = []
    google_auth = None
    if {"ga4", "google_ads"} & set(sources):
        google_auth = GoogleOAuth2(settings.google_client_id, settings.google_client_secret,
                                   settings.google_refresh_token)
    if "ga4" in sources:
        connectors.append(GA4Connector(settings.ga4_property_ids, google_auth, run_id=run_id))
    if "google_ads" in sources:
        connectors.append(GoogleAdsConnector(
            settings.google_ads_customer_ids, settings.google_ads_developer_token, google_auth,
            login_customer_id=settings.google_ads_login_customer_id,
            api_version=settings.google_ads_api_version, run_id=run_id))
    if "meta_ads" in sources:
        connectors.append(MetaAdsConnector(
            settings.meta_ad_account_ids, settings.meta_access_token,
            app_secret=settings.meta_app_secret, api_version=settings.meta_api_version,
            run_id=run_id))
    return connectors


__all__ = ["Connector", "SOURCES", "build_connectors"]
