"""Send a short Slack message when checks warn or fail.

Only problems are sent — an alert channel that posts "all good" every morning
gets muted within a week, and then the real failure goes unseen.
"""

from __future__ import annotations

import logging

from adpulse.http import HttpClient
from adpulse.quality.checks import FAIL, WARN, CheckResult

log = logging.getLogger(__name__)

ICON = {FAIL: ":red_circle:", WARN: ":large_yellow_circle:"}


def format_alert(results: list[CheckResult], run_id: str) -> str | None:
    problems = [r for r in results if r.status in (FAIL, WARN)]
    if not problems:
        return None
    problems.sort(key=lambda r: (r.status != FAIL, r.check_name, r.subject))
    n_fail = sum(r.status == FAIL for r in problems)
    n_warn = len(problems) - n_fail
    lines = [f"*AdPulse data quality* — {n_fail} failing, {n_warn} warning (run `{run_id}`)"]
    lines += [f"{ICON[r.status]} *{r.check_name}* · {r.subject}: {r.message}" for r in problems]
    return "\n".join(lines)


def send_alert(webhook_url: str, results: list[CheckResult], run_id: str,
               http: HttpClient | None = None) -> bool:
    text = format_alert(results, run_id)
    if text is None:
        return False
    if not webhook_url:
        log.warning("SLACK_WEBHOOK_URL not set — alert printed instead\n" + text)
        return False
    (http or HttpClient(name="slack", max_retries=3)).post(webhook_url, json={"text": text})
    log.info("alert sent", extra={"context": {"problems": text.count("\n")}})
    return True
