"""Command line entry point.

  adpulse run --mode demo --days 90          # full demo, no credentials needed
  adpulse run                                # live: last LOOKBACK_DAYS days, all sources
  adpulse run --sources meta_ads --start 2026-09-01 --end 2026-09-30   # backfill one source
  adpulse transform --full-refresh           # rebuild all dbt models
  adpulse check                              # quality checks only
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from adpulse.config import Settings
from adpulse.connectors import SOURCES
from adpulse.logging_utils import configure_logging
from adpulse.pipeline import RunOptions, run

STEPS = {
    "run": ("extract", "transform", "check"),
    "extract": ("extract",),
    "transform": ("transform",),
    "check": ("check",),
}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="adpulse", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=STEPS, help="which step(s) to run")
    parser.add_argument("--mode", choices=["live", "demo"], default="live",
                        help="demo = synthetic data, no API credentials required")
    parser.add_argument("--target", choices=["local", "bigquery"],
                        help="warehouse (overrides ADPULSE_TARGET)")
    parser.add_argument("--sources", default=",".join(SOURCES),
                        help=f"comma-separated subset of {', '.join(SOURCES)}")
    parser.add_argument("--start", type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--end", type=date.fromisoformat, help="YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--days", type=int, help="extract the last N complete days")
    parser.add_argument("--full-refresh", action="store_true", help="rebuild dbt models")
    parser.add_argument("--inject-anomaly", action="store_true",
                        help="demo only: spike one campaign's spend on the last day")
    parser.add_argument("--json-logs", action="store_true", help="Cloud Logging format")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging(json_logs=args.json_logs)
    settings = Settings.from_env()
    if args.target:
        settings.target = args.target

    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    unknown = set(sources) - set(SOURCES)
    if unknown:
        print(f"unknown sources: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    if args.inject_anomaly and args.mode != "demo":
        print("--inject-anomaly only works with --mode demo", file=sys.stderr)
        return 2

    end = args.end or settings.default_window()[1]
    start = args.start
    if args.days:
        start = end - timedelta(days=args.days - 1)

    opts = RunOptions(mode=args.mode, start=start, end=end, sources=sources,
                      steps=STEPS[args.command], full_refresh=args.full_refresh,
                      inject_anomaly=args.inject_anomaly)
    return run(settings, opts)


if __name__ == "__main__":
    sys.exit(main())
