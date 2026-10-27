"""Warehouse interface. BigQuery in production, DuckDB for local/CI runs.

The load contract is *idempotent by date*: loading 1–30 Sep twice leaves exactly
one copy of 1–30 Sep. That's what lets the pipeline re-pull a 30-day lookback
window every morning (ad platforms restate conversions for weeks) without ever
double-counting spend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

from adpulse.schemas import TableSchema


class Warehouse(ABC):
    @abstractmethod
    def table_ref(self, dataset: str, table: str) -> str:
        """Fully-qualified table name usable in SQL."""

    @abstractmethod
    def replace_date_range(self, dataset: str, schema: TableSchema, df: pd.DataFrame,
                           start: date, end: date) -> int:
        """Replace rows for every date in [start, end] that has data in `df`.

        Dates with *no* extracted rows are deliberately left untouched: an empty
        extract usually means an API hiccup, and wiping a day of spend because of
        one would be far worse than keeping slightly stale numbers.
        """

    @abstractmethod
    def append(self, dataset: str, schema: TableSchema, df: pd.DataFrame) -> int:
        """Append rows (used for the data-quality results log)."""

    @abstractmethod
    def query(self, sql: str) -> pd.DataFrame:
        """Run SQL and return the result."""

    def close(self) -> None:  # noqa: B027 - optional hook
        pass
