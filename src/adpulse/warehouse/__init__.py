from __future__ import annotations

from adpulse.config import Settings
from adpulse.warehouse.base import Warehouse


def get_warehouse(settings: Settings) -> Warehouse:
    if settings.target == "bigquery":
        from adpulse.warehouse.bigquery_warehouse import BigQueryWarehouse  # optional dependency

        return BigQueryWarehouse(settings)
    from adpulse.warehouse.duckdb_warehouse import DuckDBWarehouse

    return DuckDBWarehouse(settings)


__all__ = ["Warehouse", "get_warehouse"]
