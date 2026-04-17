"""Unit tests for the Copilot auth module — device flow, token exchange, caching."""
import httpx
import pytest

from sciqlop_copilot import auth


class _FakeResponse:
    def __init__(self, json_data: dict, status: int = 200):
        self._json = json_data
        self.status_code = status

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


def test_editor_headers_has_required_keys():
    h = auth.editor_headers()
    assert {"Editor-Version", "Editor-Plugin-Version", "User-Agent"} <= set(h)
    assert h["Editor-Version"].startswith("SciQLop/")


def test_request_device_code_sends_correct_request(monkeypatch):
    calls = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["url"] = url
        calls["headers"] = headers
        calls["json"] = json
        return _FakeResponse({
            "device_code": "dc-xyz",
            "user_code": "AAAA-BBBB",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        })

    monkeypatch.setattr(auth.httpx, "post", fake_post)
    code = auth.request_device_code()

    assert calls["url"] == "https://github.com/login/device/code"
    assert calls["json"] == {"client_id": "Iv1.b507a08c87ecfe98", "scope": "read:user"}
    assert calls["headers"]["Accept"] == "application/json"
    assert code.device_code == "dc-xyz"
    assert code.user_code == "AAAA-BBBB"
    assert code.expires_in == 900
    assert code.interval == 5


def test_poll_access_token_success(monkeypatch):
    monkeypatch.setattr(auth.httpx, "post", lambda *a, **kw: _FakeResponse({"access_token": "gh_abc"}))
    assert auth.poll_access_token("dc") == "gh_abc"


@pytest.mark.parametrize("err", ["authorization_pending", "slow_down"])
def test_poll_access_token_pending_returns_none(monkeypatch, err):
    monkeypatch.setattr(auth.httpx, "post", lambda *a, **kw: _FakeResponse({"error": err}))
    assert auth.poll_access_token("dc") is None


@pytest.mark.parametrize("err", ["expired_token", "access_denied", "unsupported_grant_type"])
def test_poll_access_token_terminal_errors_raise(monkeypatch, err):
    monkeypatch.setattr(
        auth.httpx,
        "post",
        lambda *a, **kw: _FakeResponse({"error": err, "error_description": "nope"}),
    )
    with pytest.raises(auth.DeviceFlowError):
        auth.poll_access_token("dc")


def test_fetch_github_user_returns_login(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse({"login": "alice", "id": 42})

    monkeypatch.setattr(auth.httpx, "get", fake_get)
    assert auth.fetch_github_user("gh-tok") == "alice"
    assert captured["url"] == "https://api.github.com/user"
    assert captured["headers"]["Authorization"] == "token gh-tok"


def test_fetch_github_user_returns_none_on_failure(monkeypatch):
    def fake_get(*a, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(auth.httpx, "get", fake_get)
    assert auth.fetch_github_user("gh-tok") is None


def test_exchange_copilot_token_uses_token_auth_header(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse({
            "token": "cop-tok",
            "expires_at": 9999,
            "endpoints": {"api": "https://api.individual.githubcopilot.com"},
        })

    monkeypatch.setattr(auth.httpx, "get", fake_get)
    tok = auth.exchange_copilot_token("gh-abc")

    assert captured["url"] == "https://api.github.com/copilot_internal/v2/token"
    assert captured["headers"]["Authorization"] == "token gh-abc"
    assert tok.token == "cop-tok"
    assert tok.expires_at == 9999
    assert tok.api_base == "https://api.individual.githubcopilot.com"


def test_exchange_copilot_token_falls_back_to_default_api_base(monkeypatch):
    monkeypatch.setattr(
        auth.httpx,
        "get",
        lambda *a, **kw: _FakeResponse({"token": "t", "expires_at": 1}),
    )
    tok = auth.exchange_copilot_token("gh-abc")
    assert tok.api_base == "https://api.githubcopilot.com"


def test_token_cache_reuses_fresh_token(monkeypatch):
    calls = {"n": 0}

    def fake_get(*a, **kw):
        calls["n"] += 1
        return _FakeResponse({
            "token": f"tok-{calls['n']}",
            "expires_at": 10_000_000_000,  # far future
            "endpoints": {"api": "https://api.individual.githubcopilot.com"},
        })

    monkeypatch.setattr(auth.httpx, "get", fake_get)
    cache = auth.CopilotTokenCache("gh-x")
    t1 = cache.get()
    t2 = cache.get()
    assert calls["n"] == 1
    assert t1 is t2


def test_token_cache_refreshes_when_within_expiry_buffer(monkeypatch):
    calls = {"n": 0}

    def fake_get(*a, **kw):
        calls["n"] += 1
        return _FakeResponse({"token": f"tok-{calls['n']}", "expires_at": 1000})

    monkeypatch.setattr(auth.httpx, "get", fake_get)
    # time.time returns 900 → remaining 100s, buffer is 60s, still fresh
    monkeypatch.setattr(auth.time, "time", lambda: 900)
    cache = auth.CopilotTokenCache("gh-x")
    cache.get()
    # now 950 → remaining 50s, within 60s buffer → refresh
    monkeypatch.setattr(auth.time, "time", lambda: 950)
    cache.get()
    assert calls["n"] == 2


def test_token_cache_refreshes_after_expiry(monkeypatch):
    calls = {"n": 0}

    def fake_get(*a, **kw):
        calls["n"] += 1
        return _FakeResponse({"token": f"tok-{calls['n']}", "expires_at": 1000})

    monkeypatch.setattr(auth.httpx, "get", fake_get)
    monkeypatch.setattr(auth.time, "time", lambda: 500)
    cache = auth.CopilotTokenCache("gh-x")
    cache.get()
    monkeypatch.setattr(auth.time, "time", lambda: 1500)
    cache.get()
    assert calls["n"] == 2
