"""GitHub Copilot auth — OAuth device flow + short-lived Copilot token exchange.

Uses the same public client ID and endpoints as copilot.vim, CopilotChat.nvim,
and the JetBrains plugin. Not officially documented by GitHub but stable.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

try:
    from importlib.metadata import version as _pkg_version

    _PLUGIN_VERSION = _pkg_version("sciqlop-copilot")
except Exception:
    _PLUGIN_VERSION = "0.0.0"

# Public client ID used by copilot.vim — published in the repo, not a secret.
_CLIENT_ID = "Iv1.b507a08c87ecfe98"
_DEVICE_CODE_URL = "https://github.com/login/device/code"
_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_DEFAULT_API_BASE = "https://api.githubcopilot.com"

_EDITOR_VERSION = f"SciQLop/{_PLUGIN_VERSION}"
_EDITOR_PLUGIN_VERSION = f"sciqlop-copilot/{_PLUGIN_VERSION}"
_USER_AGENT = f"sciqlop-copilot/{_PLUGIN_VERSION}"


def editor_headers() -> dict:
    return {
        "Editor-Version": _EDITOR_VERSION,
        "Editor-Plugin-Version": _EDITOR_PLUGIN_VERSION,
        "User-Agent": _USER_AGENT,
    }


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


@dataclass
class CopilotToken:
    token: str
    expires_at: int
    api_base: str


class DeviceFlowError(RuntimeError):
    pass


def request_device_code() -> DeviceCode:
    resp = httpx.post(
        _DEVICE_CODE_URL,
        headers={"Accept": "application/json", **editor_headers()},
        json={"client_id": _CLIENT_ID, "scope": "read:user"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return DeviceCode(
        device_code=data["device_code"],
        user_code=data["user_code"],
        verification_uri=data["verification_uri"],
        expires_in=int(data["expires_in"]),
        interval=int(data["interval"]),
    )


def poll_access_token(device_code: str) -> Optional[str]:
    """One poll step. Returns the GitHub OAuth token on success, None while pending.

    Raises DeviceFlowError on terminal errors (expired, denied, …).
    """
    resp = httpx.post(
        _ACCESS_TOKEN_URL,
        headers={"Accept": "application/json", **editor_headers()},
        json={
            "client_id": _CLIENT_ID,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" in data:
        return data["access_token"]
    err = data.get("error")
    if err in (None, "authorization_pending", "slow_down"):
        return None
    raise DeviceFlowError(data.get("error_description") or err or "unknown device-flow error")


def wait_for_access_token(
    code: DeviceCode,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """Blocking poll loop — useful from scripts/REPL. Qt UI should poll on its own timer."""
    deadline = time.monotonic() + code.expires_in
    interval = max(code.interval, 1)
    while time.monotonic() < deadline:
        if should_cancel and should_cancel():
            raise DeviceFlowError("cancelled")
        token = poll_access_token(code.device_code)
        if token:
            return token
        time.sleep(interval)
    raise DeviceFlowError("device code expired — sign-in timed out")


def fetch_github_user(github_token: str) -> Optional[str]:
    """Return the GitHub login for the given user token, or None on failure."""
    try:
        resp = httpx.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github+json",
                **editor_headers(),
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("login")
    except Exception:
        return None


def exchange_copilot_token(github_token: str) -> CopilotToken:
    """Swap the long-lived GitHub OAuth token for a short-lived Copilot token."""
    resp = httpx.get(
        _COPILOT_TOKEN_URL,
        headers={
            "Authorization": f"token {github_token}",
            "Accept": "application/json",
            **editor_headers(),
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    api_base = data.get("endpoints", {}).get("api", _DEFAULT_API_BASE)
    return CopilotToken(
        token=data["token"],
        expires_at=int(data.get("expires_at", 0)),
        api_base=api_base,
    )


class CopilotTokenCache:
    """Caches the short-lived Copilot token and refreshes it before expiry."""

    _REFRESH_BUFFER_SEC = 60

    def __init__(self, github_token: str):
        self._github_token = github_token
        self._cached: Optional[CopilotToken] = None

    def get(self) -> CopilotToken:
        now = int(time.time())
        if self._cached and self._cached.expires_at - now > self._REFRESH_BUFFER_SEC:
            return self._cached
        self._cached = exchange_copilot_token(self._github_token)
        return self._cached
