from __future__ import annotations

import logging

import duckdb
import pandas as pd

from adpulse.config import Settings
from adpulse.schemas import TableSchema
from adpulse.warehouse.base import Warehouse

log = logging.getLogger(__name__)

_DUCK_TYPES = {"STRING": "VARCHAR", "INT64": "BIGINT", "FLOAT64": "DOUBLE",
               "DATE": "DATE", "TIMESTAMP": "TIMESTAMPTZ"}


class DuckDBWarehouse(Warehouse):
    """Local stand-in for BigQuery: same datasets (schemas), same tables, same contract."""

    def __init__(self, settings: Settings):
        settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = settings.duckdb_path
        self.con = duckdb.connect(str(self.path))

    def table_ref(self, dataset: str, table: str) -> str:
        return f"{dataset}.{table}"

    def _ensure_table(self, dataset: str, schema: TableSchema) -> str:
        ref = self.table_ref(dataset, schema.name)
        cols = ", ".join(f"{c.name} {_DUCK_TYPES[c.type]}" for c in schema.columns)
        self.con.execute(f"CREATE SCHEMA IF NOT EXISTS {dataset}")
        self.con.execute(f"CREATE TABLE IF NOT EXISTS {ref} ({cols})")
        return ref

    def replace_date_range(self, dataset, schema, df, start, end) -> int:
        ref = self._ensure_table(dataset, schema)
        part = schema.partition_field
        dates = sorted(set(df[part])) if len(df) else []
        if not dates:
            log.warning("empty extract — nothing replaced", extra={"context": {"table": ref}})
            return 0
        self.con.execute("BEGIN TRANSACTION")
        try:
            self.con.execute(f"DELETE FROM {ref} WHERE {part} IN (SELECT UNNEST(?))", [dates])
            self.con.register("incoming", df)
            self.con.execute(f"INSERT INTO {ref} SELECT {', '.join(schema.column_names)} "
                             f"FROM incoming")
            self.con.unregister("incoming")
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        skipped = (end - start).days + 1 - len(dates)
        log.info("loaded", extra={"context": {"table": ref, "rows": len(df),
                                              "days": len(dates), "empty_days_kept": skipped}})
        return len(df)

    def append(self, dataset, schema, df) -> int:
        ref = self._ensure_table(dataset, schema)
        if df.empty:
            return 0
        self.con.register("incoming", df)
        self.con.execute(f"INSERT INTO {ref} SELECT {', '.join(schema.column_names)} "
                         f"FROM incoming")
        self.con.unregister("incoming")
        return len(df)

    def query(self, sql: str) -> pd.DataFrame:
        return self.con.execute(sql).df()

    def close(self) -> None:
        self.con.close()
