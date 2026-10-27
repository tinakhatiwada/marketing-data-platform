"""A small, well-behaved HTTP client shared by every connector.

What it handles (and why):
  * Retries with exponential backoff + full jitter on 429 / 5xx / network errors,
    so a transient blip at 6am doesn't leave the dashboards stale all day.
  * Honours `Retry-After` when the API tells us exactly how long to wait.
  * Client-side rate limiting (requests per minute) so we stay under quotas
    instead of discovering them via errors.
  * A per-connector hook (`is_retryable`) because not every API signals throttling
    with a 429 — Meta, for example, returns HTTP 400 with error code 17/80004.
  * Never logs query strings, because some APIs (Meta) put tokens in the URL.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.payload = payload


class RateLimiter:
    """Spaces requests evenly so we never exceed `per_minute` calls."""

    def __init__(self, per_minute: float | None, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = 60.0 / per_minute if per_minute else 0.0
        self._clock, self._sleep = clock, sleep
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if not self.min_interval:
            return
        with self._lock:
            now = self._clock()
            if now < self._next_allowed:
                self._sleep(self._next_allowed - now)
                now = self._next_allowed
            self._next_allowed = now + self.min_interval


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


class HttpClient:
    def __init__(
        self,
        *,
        name: str,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        backoff_cap: float = 60.0,
        requests_per_minute: float | None = None,
        timeout: float = 60.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        is_retryable: Callable[[requests.Response], bool] | None = None,
    ):
        self.name = name
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.timeout = timeout
        self.session = session or requests.Session()
        self._sleep = sleep
        self._limiter = RateLimiter(requests_per_minute, sleep=sleep)
        self._is_retryable = is_retryable
        self.request_count = 0

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.backoff_cap)
            except ValueError:
                pass  # HTTP-date form; fall back to exponential backoff
        # "Full jitter" — spreads retries out so parallel jobs don't stampede.
        return random.uniform(0, min(self.backoff_cap, self.backoff_base * 2**attempt))

    def request(self, method: str, url: str, **kwargs: Any) -> dict:
        kwargs.setdefault("timeout", self.timeout)
        for attempt in range(self.max_retries + 1):
            self._limiter.wait()
            self.request_count += 1
            try:
                resp = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == self.max_retries:
                    raise
                delay = self._backoff(attempt, None)
                log.warning(
                    "network error, retrying",
                    extra={"context": {"api": self.name, "url": _safe_url(url),
                                       "attempt": attempt + 1, "delay_s": round(delay, 2),
                                       "error": type(exc).__name__}},
                )
                self._sleep(delay)
                continue

            if resp.ok:
                return resp.json() if resp.content else {}

            retryable = resp.status_code in RETRYABLE_STATUS or (
                self._is_retryable is not None and self._is_retryable(resp)
            )
            if retryable and attempt < self.max_retries:
                delay = self._backoff(attempt, resp.headers.get("Retry-After"))
                log.warning(
                    "retryable API error",
                    extra={"context": {"api": self.name, "url": _safe_url(url),
                                       "status": resp.status_code, "attempt": attempt + 1,
                                       "delay_s": round(delay, 2)}},
                )
                self._sleep(delay)
                continue

            try:
                payload = resp.json()
            except ValueError:
                payload = resp.text[:500]
            raise ApiError(resp.status_code, f"{self.name} {_safe_url(url)}", payload)

        raise AssertionError("unreachable")  # pragma: no cover

    def get(self, url: str, **kwargs: Any) -> dict:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> dict:
        return self.request("POST", url, **kwargs)
