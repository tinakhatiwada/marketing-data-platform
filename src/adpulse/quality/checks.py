"""Operational data-quality checks that run after every load + dbt build.

dbt tests answer "is the data *internally* consistent?" (grain, nulls, joins).
These checks answer "does today's data look like the real world?":

  freshness        Did every source deliver data up to yesterday?
  volume           Is yesterday's row count in line with the last week?
  spend_anomaly    Did any client's spend jump or crash (budget typo, paused account)?
  ga4_tracking     Did GA4 sessions collapse (tag removed during a site release)?
  reconciliation   Does the reporting table still sum to the fact table?

Each produces pass / warn / fail, written to `ops.data_quality_results` so the
dashboard has a "pipeline health" page and nobody has to read logs.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from adpulse.config import Settings
from adpulse.schemas import ALL_RAW_TABLES, DATA_QUALITY_RESULTS, conform
from adpulse.warehouse.base import Warehouse

log = logging.getLogger(__name__)

PASS, WARN, FAIL = "pass", "warn", "fail"


@dataclass
class CheckResult:
    check_name: str
    subject: str
    status: str
    message: str
    observed_value: float | None = None
    threshold: str | None = None


def _d(value: date) -> str:
    return f"DATE '{value.isoformat()}'"


class QualityChecker:
    def __init__(self, wh: Warehouse, settings: Settings, run_id: str, as_of: date):
        self.wh = wh
        self.s = settings
        self.run_id = run_id
        self.as_of = as_of  # the latest complete day we expect data for

    # ------------------------------------------------------------------ helpers --
    def _raw(self, table: str) -> str:
        return self.wh.table_ref(self.s.raw_dataset, table)

    def _mart(self, table: str) -> str:
        return self.wh.table_ref(self.s.analytics_dataset, table)

    # ------------------------------------------------------------------- checks --
    def freshness(self) -> list[CheckResult]:
        results = []
        for table in ALL_RAW_TABLES:
            df = self.wh.query(f"SELECT MAX(report_date) AS max_date FROM {self._raw(table)}")
            max_date = df["max_date"].iloc[0]
            if max_date is None or pd.isna(max_date):
                results.append(CheckResult("freshness", table, FAIL, "table is empty"))
                continue
            lag = (self.as_of - pd.Timestamp(max_date).date()).days
            status = PASS if lag <= 0 else WARN if lag == 1 else FAIL
            results.append(CheckResult(
                "freshness", table, status,
                f"latest data {pd.Timestamp(max_date).date()} ({lag} day(s) behind {self.as_of})",
                float(lag), "0 days = pass, 1 = warn, 2+ = fail"))
        return results

    def volume(self) -> list[CheckResult]:
        results = []
        start = self.as_of - timedelta(days=7)
        for table in ALL_RAW_TABLES:
            df = self.wh.query(
                f"SELECT report_date, COUNT(*) AS n FROM {self._raw(table)} "
                f"WHERE report_date BETWEEN {_d(start)} AND {_d(self.as_of)} GROUP BY 1")
            df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
            today = df.loc[df["report_date"] == self.as_of, "n"].sum()
            history = df.loc[df["report_date"] < self.as_of, "n"]
            if history.empty:
                results.append(CheckResult("volume", table, PASS, "no history yet — skipped"))
                continue
            baseline = float(history.median())
            ratio = today / baseline if baseline else 1.0
            status = PASS if ratio >= 0.8 else WARN if ratio >= 0.5 else FAIL
            results.append(CheckResult(
                "volume", table, status,
                f"{int(today)} rows on {self.as_of} vs 7-day median {baseline:.0f}",
                round(ratio, 3), "ratio >= 0.8 pass, >= 0.5 warn, else fail"))
        return results

    def spend_anomaly(self) -> list[CheckResult]:
        start = self.as_of - timedelta(days=14)
        df = self.wh.query(
            f"SELECT client_code, platform, report_date, SUM(spend_aud) AS spend "
            f"FROM {self._mart('fct_paid_media_daily')} "
            f"WHERE report_date BETWEEN {_d(start)} AND {_d(self.as_of)} GROUP BY 1, 2, 3")
        df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
        results = []
        for (client, platform), g in df.groupby(["client_code", "platform"]):
            subject = f"{client}/{platform}"
            today = float(g.loc[g["report_date"] == self.as_of, "spend"].sum())
            history = g.loc[g["report_date"] < self.as_of, "spend"]
            if len(history) < 7:
                results.append(CheckResult("spend_anomaly", subject, PASS,
                                           "under 7 days of history — skipped"))
                continue
            baseline = float(history.mean())
            if baseline > 0 and today == 0:
                results.append(CheckResult(
                    "spend_anomaly", subject, FAIL,
                    f"zero spend on {self.as_of} (14-day avg AUD {baseline:,.0f}) — "
                    f"paused account, billing issue or missing data?", 0.0, "> 0"))
                continue
            change = (today - baseline) / baseline if baseline else 0.0
            status = PASS if abs(change) <= 0.5 else WARN if abs(change) <= 1.5 else FAIL
            results.append(CheckResult(
                "spend_anomaly", subject, status,
                f"AUD {today:,.0f} on {self.as_of} vs 14-day avg AUD {baseline:,.0f} "
                f"({change:+.0%})",
                round(change, 3), "|change| <= 50% pass, <= 150% warn, else fail"))
        return results

    def ga4_tracking(self) -> list[CheckResult]:
        start = self.as_of - timedelta(days=7)
        df = self.wh.query(
            f"SELECT client_code, report_date, SUM(sessions) AS sessions "
            f"FROM {self._mart('fct_web_traffic_daily')} "
            f"WHERE report_date BETWEEN {_d(start)} AND {_d(self.as_of)} GROUP BY 1, 2")
        df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
        results = []
        for client, g in df.groupby("client_code"):
            today = float(g.loc[g["report_date"] == self.as_of, "sessions"].sum())
            history = g.loc[g["report_date"] < self.as_of, "sessions"]
            if history.empty:
                continue
            baseline = float(history.median())
            ratio = today / baseline if baseline else 1.0
            status = PASS if ratio >= 0.6 else WARN if ratio >= 0.3 else FAIL
            results.append(CheckResult(
                "ga4_tracking", client, status,
                f"{today:,.0f} sessions vs 7-day median {baseline:,.0f}",
                round(ratio, 3), "ratio >= 0.6 pass, >= 0.3 warn, else fail"))
        return results

    def reconciliation(self) -> list[CheckResult]:
        start = self.as_of - timedelta(days=self.s.lookback_days)
        where = f"WHERE report_date BETWEEN {_d(start)} AND {_d(self.as_of)}"
        fact = self.wh.query(
            f"SELECT SUM(spend_aud) AS s FROM {self._mart('fct_paid_media_daily')} {where}")
        rpt = self.wh.query(
            f"SELECT SUM(spend_aud) AS s FROM {self._mart('rpt_client_channel_daily')} {where}")
        a, b = float(fact["s"].iloc[0] or 0), float(rpt["s"].iloc[0] or 0)
        diff = abs(a - b)
        return [CheckResult(
            "reconciliation", "rpt_client_channel_daily", PASS if diff < 0.01 else FAIL,
            f"fact AUD {a:,.2f} vs report AUD {b:,.2f}", round(diff, 4), "difference < 0.01")]

    # --------------------------------------------------------------------- run ----
    def run_all(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        for check in (self.freshness, self.volume, self.spend_anomaly,
                      self.ga4_tracking, self.reconciliation):
            try:
                results.extend(check())
            except Exception as exc:  # a broken check must not hide the others
                log.exception("check crashed")
                results.append(CheckResult(check.__name__, "-", FAIL, f"check errored: {exc}"))
        return results

    def save(self, results: list[CheckResult]) -> None:
        now = datetime.now(timezone.utc)
        df = pd.DataFrame([asdict(r) for r in results])
        df["checked_date"] = now.date()
        df["checked_at"] = now
        df["run_id"] = self.run_id
        self.wh.append(self.s.ops_dataset, DATA_QUALITY_RESULTS,
                       conform(df, DATA_QUALITY_RESULTS))
