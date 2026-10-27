from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone

import pandas as pd

from adpulse.schemas import TableSchema, conform


class Connector(ABC):
    """A source system. Subclasses return rows matching their raw table schema."""

    name: str
    schema: TableSchema

    def __init__(self, run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex[:12]

    @abstractmethod
    def fetch(self, start: date, end: date) -> list[dict]:
        """Return raw rows (dicts keyed by schema column names, minus metadata)."""

    def extract(self, start: date, end: date) -> pd.DataFrame:
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        rows = self.fetch(start, end)
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=[c for c in self.schema.column_names
                                       if not c.startswith("_")])
        df["_extracted_at"] = datetime.now(timezone.utc)
        df["_run_id"] = self.run_id
        return conform(df, self.schema)
