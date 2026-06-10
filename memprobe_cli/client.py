from __future__ import annotations

from typing import Optional

import requests

from . import __version__, config


class ApiError(Exception):
    pass


class AuthError(ApiError):
    pass


class QuotaError(ApiError):
    pass


_TIMEOUT = 60
_NO_KEY = (
    "No API key configured. Create one at https://memprobe.dev "
    "(Account settings -> API keys), then run:  memprobe config set --key <key>"
)


def _request(method: str, endpoint: str, payload: Optional[dict] = None) -> dict:
    key = config.get_api_key()
    if not key:
        raise AuthError(_NO_KEY)
    url = config.get_server() + endpoint
    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": f"memprobe-cli/{__version__}",
    }
    try:
        resp = requests.request(method, url, json=payload, headers=headers, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise ApiError(f"Could not reach {url}: {exc}") from exc

    if resp.status_code == 401:
        raise AuthError("API key was rejected. Check it with:  memprobe config show")
    if resp.status_code in (402, 429):
        raise QuotaError(_message(resp))
    if resp.status_code >= 400:
        raise ApiError(_message(resp))
    try:
        return resp.json()
    except ValueError as exc:
        raise ApiError("Unexpected non-JSON response from the server.") from exc


def _message(resp) -> str:
    try:
        body = resp.json()
        return body.get("error") or body.get("detail") or resp.text or f"HTTP {resp.status_code}"
    except ValueError:
        return resp.text.strip() or f"HTTP {resp.status_code}"


def analyze(metadata: dict, project: Optional[str] = None) -> dict:
    return _request("post", "/api/analyze", {"metadata": metadata, "project": project})


def check(metadata: dict, budgets: dict) -> dict:
    return _request("post", "/api/check", {"metadata": metadata, "budgets": budgets})


def diff(base: dict, head: dict, fail_on: Optional[dict] = None) -> dict:
    return _request("post", "/api/diff", {"base": base, "head": head, "fail_on": fail_on or {}})


def diff_project(head: dict, project: str, fail_on: Optional[dict] = None) -> dict:
    return _request("post", "/api/diff", {"head": head, "project": project, "fail_on": fail_on or {}})


def account() -> dict:
    return _request("get", "/api/account")
