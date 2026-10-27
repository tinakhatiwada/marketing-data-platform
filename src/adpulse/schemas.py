"""Raw-layer table contracts.

One place defines every raw table's columns, types, partitioning and clustering.
Both warehouse backends (BigQuery and local DuckDB) build their DDL from this, and
connectors are validated against it before anything is loaded — so a renamed API
field fails loudly at extract time instead of silently producing NULLs in a client
dashboard.

Naming conventions (applied everywhere downstream too):
  * snake_case, no abbreviations except well-known ones (id, ctr).
  * `report_date` is always the partition column and always the platform's local date.
  * money columns carry their unit: `cost_micros`, `spend`, `*_local`, `*_aud`.
  * `_extracted_at` / `_run_id` are pipeline metadata for lineage and dedup.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # BigQuery standard SQL type
    description: str
    required: bool = True


@dataclass(frozen=True)
class TableSchema:
    name: str
    description: str
    columns: tuple[Column, ...]
    partition_field: str = "report_date"
    cluster_fields: tuple[str, ...] = field(default_factory=tuple)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


_META = (
    Column("_extracted_at", "TIMESTAMP", "UTC time the row was pulled from the API."),
    Column("_run_id", "STRING", "Pipeline run that produced the row (for lineage)."),
)

GA4_TRAFFIC_DAILY = TableSchema(
    name="ga4_traffic_daily",
    description="GA4 Data API runReport: sessions and key events by source/medium/campaign.",
    cluster_fields=("property_id", "session_medium"),
    columns=(
        Column("report_date", "DATE", "Date in the GA4 property's timezone."),
        Column("property_id", "STRING", "GA4 property id."),
        Column("session_source", "STRING", "sessionSource dimension."),
        Column("session_medium", "STRING", "sessionMedium dimension."),
        Column("session_campaign_name", "STRING", "sessionCampaignName (utm_campaign)."),
        Column("sessions", "INT64", "Sessions."),
        Column("engaged_sessions", "INT64", "Engaged sessions."),
        Column("key_events", "FLOAT64", "Key events (formerly 'conversions' in GA4)."),
        Column("total_revenue", "FLOAT64", "Total revenue in property currency."),
        Column("currency_code", "STRING", "Property currency (ISO 4217)."),
        *_META,
    ),
)

GOOGLE_ADS_CAMPAIGN_DAILY = TableSchema(
    name="google_ads_campaign_daily",
    description="Google Ads API (GAQL, FROM campaign) daily campaign performance.",
    cluster_fields=("customer_id", "campaign_id"),
    columns=(
        Column("report_date", "DATE", "segments.date (account timezone)."),
        Column("customer_id", "STRING", "Google Ads customer id, digits only."),
        Column("campaign_id", "STRING", "campaign.id."),
        Column("campaign_name", "STRING", "campaign.name at extract time."),
        Column("campaign_status", "STRING", "campaign.status."),
        Column("channel_type", "STRING", "campaign.advertising_channel_type."),
        Column("currency_code", "STRING", "customer.currency_code."),
        Column("impressions", "INT64", "metrics.impressions."),
        Column("clicks", "INT64", "metrics.clicks."),
        Column("cost_micros", "INT64", "metrics.cost_micros (1,000,000 = 1 unit)."),
        Column("conversions", "FLOAT64", "metrics.conversions (fractional by design)."),
        Column("conversions_value", "FLOAT64", "metrics.conversions_value."),
        *_META,
    ),
)

META_ADS_CAMPAIGN_DAILY = TableSchema(
    name="meta_ads_campaign_daily",
    description="Meta Marketing API /insights, level=campaign, time_increment=1.",
    cluster_fields=("account_id", "campaign_id"),
    columns=(
        Column("report_date", "DATE", "date_start (ad account timezone)."),
        Column("account_id", "STRING", "Ad account id without the act_ prefix."),
        Column("campaign_id", "STRING", "campaign_id."),
        Column("campaign_name", "STRING", "campaign_name at extract time."),
        Column("objective", "STRING", "Campaign objective."),
        Column("currency_code", "STRING", "account_currency."),
        Column("impressions", "INT64", "impressions."),
        Column("clicks_all", "INT64", "clicks (all clicks, incl. likes/expands)."),
        Column("link_clicks", "INT64", "inline_link_clicks — comparable to Google clicks."),
        Column("spend", "FLOAT64", "spend in account currency."),
        Column("conversions", "FLOAT64",
               "Primary conversions: first action type found in the priority list."),
        Column("conversion_value", "FLOAT64", "Value for the same action type."),
        Column("conversion_action_type", "STRING", "Which action_type was counted.",
               required=False),
        Column("actions_json", "STRING", "Raw actions array, kept for re-processing.",
               required=False),
        *_META,
    ),
)

ALL_RAW_TABLES = {t.name: t for t in (GA4_TRAFFIC_DAILY, GOOGLE_ADS_CAMPAIGN_DAILY,
                                      META_ADS_CAMPAIGN_DAILY)}

DATA_QUALITY_RESULTS = TableSchema(
    name="data_quality_results",
    description="One row per data-quality check per pipeline run. Powers the health page.",
    partition_field="checked_date",
    cluster_fields=("check_name",),
    columns=(
        Column("checked_date", "DATE", "Run date (partition)."),
        Column("checked_at", "TIMESTAMP", "Run time (UTC)."),
        Column("run_id", "STRING", "Pipeline run id."),
        Column("check_name", "STRING", "Check identifier."),
        Column("subject", "STRING", "Table / client / source the check was about."),
        Column("status", "STRING", "pass | warn | fail."),
        Column("observed_value", "FLOAT64", "What we measured.", required=False),
        Column("threshold", "STRING", "What we compared against.", required=False),
        Column("message", "STRING", "Human-readable explanation."),
    ),
)

_PANDAS_TYPES = {"STRING": "string", "INT64": "Int64", "FLOAT64": "float64"}


class SchemaError(ValueError):
    pass


def conform(df: pd.DataFrame, schema: TableSchema) -> pd.DataFrame:
    """Validate a connector's DataFrame against the contract and coerce dtypes."""
    missing = [c.name for c in schema.columns if c.name not in df.columns and c.required]
    if missing:
        raise SchemaError(f"{schema.name}: missing columns {missing}")
    unexpected = set(df.columns) - set(schema.column_names)
    if unexpected:
        raise SchemaError(f"{schema.name}: unexpected columns {sorted(unexpected)}")

    out = df.copy()
    for col in schema.columns:
        if col.name not in out.columns:
            out[col.name] = None
        if col.type == "DATE":
            out[col.name] = pd.to_datetime(out[col.name]).dt.date
        elif col.type == "TIMESTAMP":
            out[col.name] = pd.to_datetime(out[col.name], utc=True)
        else:
            out[col.name] = out[col.name].astype(_PANDAS_TYPES[col.type])

    null_required = [
        c.name for c in schema.columns
        if c.required and c.name in ("report_date", "checked_date") and out[c.name].isna().any()
    ]
    if null_required:
        raise SchemaError(f"{schema.name}: NULLs in partition column {null_required}")
    return out[schema.column_names]
