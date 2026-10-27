import pytest
import requests

from adpulse.http import ApiError, HttpClient, RateLimiter
from tests.conftest import FakeResponse, FakeSession


def client(session, sleep, **kw):
    return HttpClient(name="test", session=session, sleep=sleep, **kw)


def test_retries_429_then_succeeds_honouring_retry_after(fake_sleep, sleeps):
    session = FakeSession([
        FakeResponse(429, {"error": "slow down"}, {"Retry-After": "7"}),
        FakeResponse(200, {"ok": True}),
    ])
    assert client(session, fake_sleep).get("https://api.example/x") == {"ok": True}
    assert sleeps == [7.0]
    assert len(session.calls) == 2


def test_retries_network_errors(fake_sleep):
    session = FakeSession([requests.ConnectionError("reset"), FakeResponse(200, {"ok": 1})])
    assert client(session, fake_sleep).get("https://api.example/x") == {"ok": 1}


def test_gives_up_after_max_retries(fake_sleep, sleeps):
    session = FakeSession([FakeResponse(503) for _ in range(4)])
    with pytest.raises(ApiError) as err:
        client(session, fake_sleep, max_retries=3).get("https://api.example/x")
    assert err.value.status == 503
    assert len(sleeps) == 3


def test_client_errors_are_not_retried(fake_sleep, sleeps):
    session = FakeSession([FakeResponse(400, {"error": {"message": "bad field"}})])
    with pytest.raises(ApiError) as err:
        client(session, fake_sleep).get("https://api.example/x")
    assert err.value.payload == {"error": {"message": "bad field"}}
    assert sleeps == []


def test_custom_retry_predicate(fake_sleep):
    session = FakeSession([FakeResponse(400, {"code": "throttled"}), FakeResponse(200, {})])
    c = client(session, fake_sleep, is_retryable=lambda r: r.json().get("code") == "throttled")
    assert c.get("https://api.example/x") == {}


def test_error_message_never_contains_query_string(fake_sleep):
    session = FakeSession([FakeResponse(401)])
    with pytest.raises(ApiError) as err:
        client(session, fake_sleep).get("https://graph.example/v1?access_token=SECRET")
    assert "SECRET" not in str(err.value)


def test_rate_limiter_spaces_calls():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    limiter = RateLimiter(per_minute=60, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        limiter.wait()
    assert slept == [1.0, 1.0]
