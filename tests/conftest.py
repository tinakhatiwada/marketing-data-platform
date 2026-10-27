from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest
import requests


class FakeResponse(requests.Response):
    def __init__(self, status: int = 200, payload=None, headers: dict | None = None):
        super().__init__()
        self.status_code = status
        self._content = json.dumps(payload if payload is not None else {}).encode()
        self.headers.update(headers or {})


@dataclass
class FakeSession:
    """Replays queued responses and records every request made."""

    responses: list = field(default_factory=list)
    calls: list = field(default_factory=list)

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeAuth:
    def headers(self):
        return {"Authorization": "Bearer test-token"}


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def fake_sleep(sleeps):
    return sleeps.append
