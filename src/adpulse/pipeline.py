"""Orchestrates one pipeline run: extract → load → dbt build → quality checks → alert.

Designed to run as a Cloud Run job triggered by Cloud Scheduler each morning,
but every step can also be run on its own from the CLI.

Exit codes (Cloud Run marks the execution failed on non-zero, which in turn
fires a Cloud Monitoring alert — a second, independent alerting path):
  0  success (warnings allowed)
  1  a data-quality check failed
  2  extraction, load or dbt failed
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date

from adpulse.config import PROJECT_ROOT, Settings
from adpulse.connectors import SOURCES, build_connectors
from adpulse.quality import FAIL, QualityChecker, send_alert
from adpulse.warehouse import get_warehouse

log = logging.getLogger("adpulse.pipeline")

DBT_DIR = PROJECT_ROOT / "dbt"


@dataclass
class RunOptions:
    mode: str = "live"  # live | demo
    start: date | None = None
    end: date | None = None
    sources: tuple[str, ...] = SOURCES
    steps: tuple[str, ...] = ("extract", "transform", "check")
    full_refresh: bool = False
    inject_anomaly: bool = False
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


def extract_and_load(settings: Settings, opts: RunOptions, start: date, end: date) -> dict:
    wh = get_warehouse(settings)
    loaded = {}
    try:
        connectors = build_connectors(
            settings, mode=opts.mode, sources=opts.sources, run_id=opts.run_id,
            anomaly_date=end if opts.inject_anomaly else None)
        for connector in connectors:
            t0 = time.monotonic()
            df = connector.extract(start, end)
            n = wh.replace_date_range(settings.raw_dataset, connector.schema, df, start, end)
            loaded[connector.name] = n
            log.info("source done", extra={"context": {
                "source": connector.name, "rows": n, "seconds": round(time.monotonic() - t0, 1)}})
    finally:
        wh.close()  # DuckDB allows one writer: release the file before dbt opens it
    return loaded


def run_dbt(settings: Settings, full_refresh: bool = False, command: str = "build") -> None:
    dbt = shutil.which("dbt")
    if dbt is None:
        raise RuntimeError("dbt is not installed (pip install -e '.[dev]')")
    args = [dbt, command, "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR),
            "--target", "bigquery" if settings.target == "bigquery" else "local",
            "--vars", json.dumps({"lookback_days": settings.lookback_days})]
    if full_refresh:
        args.append("--full-refresh")
    env = {**os.environ,
           "DUCKDB_PATH": str(settings.duckdb_path),
           "RAW_DATASET": settings.raw_dataset,
           "GCP_PROJECT": settings.gcp_project,
           "BQ_LOCATION": settings.bq_location}
    log.info("running dbt", extra={"context": {"command": command,
                                               "full_refresh": full_refresh}})
    proc = subprocess.run(args, env=env, cwd=DBT_DIR, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"dbt {command} failed with exit code {proc.returncode}")


def run_checks(settings: Settings, opts: RunOptions, as_of: date) -> int:
    wh = get_warehouse(settings)
    try:
        checker = QualityChecker(wh, settings, opts.run_id, as_of)
        results = checker.run_all()
        checker.save(results)
    finally:
        wh.close()

    width = max(len(f"{r.check_name} {r.subject}") for r in results)
    print("\nData quality results")
    print("-" * (width + 50))
    for r in results:
        label = f"{r.check_name} {r.subject}"
        print(f"  {r.status.upper():<5} {label:<{width}}  {r.message}")
    print()

    send_alert(settings.slack_webhook_url, results, opts.run_id)
    return 1 if any(r.status == FAIL for r in results) else 0


def run(settings: Settings, opts: RunOptions) -> int:
    default_start, default_end = settings.default_window()
    start, end = opts.start or default_start, opts.end or default_end
    log.info("pipeline start", extra={"context": {
        "run_id": opts.run_id, "mode": opts.mode, "target": settings.target,
        "start": str(start), "end": str(end), "steps": list(opts.steps)}})
    try:
        if "extract" in opts.steps:
            extract_and_load(settings, opts, start, end)
        if "transform" in opts.steps:
            run_dbt(settings, full_refresh=opts.full_refresh)
    except Exception:
        log.exception("pipeline failed")
        return 2

    code = run_checks(settings, opts, as_of=end) if "check" in opts.steps else 0
    log.info("pipeline finished", extra={"context": {"run_id": opts.run_id, "exit_code": code}})
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(Settings.from_env(), RunOptions()))
