"""BigQuery warehouse.

Loading strategy: one load job per day into the day's partition using a partition
decorator (`table$YYYYMMDD`) with WRITE_TRUNCATE. Why this rather than
DELETE + INSERT or MERGE?

  * It's atomic per day and naturally idempotent.
  * Load jobs are free; DML statements are billed by bytes scanned.
  * It works in the BigQuery free sandbox, which doesn't allow DML at all.

Raw tables are partitioned by `report_date` and clustered by account/campaign so
downstream models only scan the days they rebuild.
"""

from __future__ import annotations

import logging

import pandas as pd
from google.cloud import bigquery

from adpulse.config import Settings
from adpulse.schemas import TableSchema
from adpulse.warehouse.base import Warehouse

log = logging.getLogger(__name__)


def _bq_schema(schema: TableSchema) -> list[bigquery.SchemaField]:
    return [
        bigquery.SchemaField(c.name, c.type,
                             mode="REQUIRED" if c.name == schema.partition_field else "NULLABLE",
                             description=c.description)
        for c in schema.columns
    ]


class BigQueryWarehouse(Warehouse):
    def __init__(self, settings: Settings, client: bigquery.Client | None = None):
        if not settings.gcp_project:
            raise ValueError("GCP_PROJECT must be set for the bigquery target")
        self.project = settings.gcp_project
        self.location = settings.bq_location
        self.client = client or bigquery.Client(project=self.project, location=self.location)
        self._ensured: set[str] = set()

    def table_ref(self, dataset: str, table: str) -> str:
        return f"`{self.project}.{dataset}.{table}`"

    def _ensure_table(self, dataset: str, schema: TableSchema) -> str:
        table_id = f"{self.project}.{dataset}.{schema.name}"
        if table_id in self._ensured:
            return table_id
        ds = bigquery.Dataset(f"{self.project}.{dataset}")
        ds.location = self.location
        self.client.create_dataset(ds, exists_ok=True)
        table = bigquery.Table(table_id, schema=_bq_schema(schema))
        table.description = schema.description
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY, field=schema.partition_field)
        if schema.cluster_fields:
            table.clustering_fields = list(schema.cluster_fields)
        self.client.create_table(table, exists_ok=True)
        self._ensured.add(table_id)
        return table_id

    def replace_date_range(self, dataset, schema, df, start, end) -> int:
        table_id = self._ensure_table(dataset, schema)
        part = schema.partition_field
        if df.empty:
            log.warning("empty extract — nothing replaced", extra={"context": {"table": table_id}})
            return 0
        job_config = bigquery.LoadJobConfig(
            schema=_bq_schema(schema),
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            time_partitioning=bigquery.TimePartitioning(field=part),
        )
        loaded = 0
        for day, day_df in df.groupby(part, sort=True):
            dest = f"{table_id}${pd.Timestamp(day):%Y%m%d}"
            self.client.load_table_from_dataframe(day_df, dest, job_config=job_config).result()
            loaded += len(day_df)
        log.info("loaded", extra={"context": {"table": table_id, "rows": loaded,
                                              "start": str(start), "end": str(end)}})
        return loaded

    def append(self, dataset, schema, df) -> int:
        table_id = self._ensure_table(dataset, schema)
        if df.empty:
            return 0
        job_config = bigquery.LoadJobConfig(
            schema=_bq_schema(schema),
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        self.client.load_table_from_dataframe(df, table_id, job_config=job_config).result()
        return len(df)

    def query(self, sql: str) -> pd.DataFrame:
        # Hard cap on bytes so a bad query can never run up a surprise bill.
        cfg = bigquery.QueryJobConfig(maximum_bytes_billed=5 * 1024**3)
        return self.client.query(sql, job_config=cfg).result().to_dataframe()
