"""HTTP client for the memprobe Lite API.

Sends extracted metadata to the server, which runs the analysis and returns
results. Auth is a Bearer API key. All errors are raised as :class:`ApiError`
(or a subclass) with a message suitable for showing the user directly.
"""

from __future__ import annotations

from typing import Optional

import requests

from . import __version__, config


class ApiError(Exception):
    """Any failure talking to the API."""


class AuthError(ApiError):
    """Missing or rejected API key."""


class QuotaError(ApiError):
    """Rate limit or account quota exceeded."""


_TIMEOUT = 60


def _post(endpoint: str, payload: dict) -> dict:
    key = config.get_api_key()
    if not key:
        raise AuthError(
            "No API key configured. Create one at https://memprobe.dev "
            "(Account -> API keys), then run:  memprobe config set --key <key>"
        )
    url = config.get_server() + endpoint
    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": f"memprobe-cli/{__version__}",
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
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
        raise ApiError("The server returned an unexpected (non-JSON) response.") from exc


def _message(resp) -> str:
    try:
        body = resp.json()
        return body.get("error") or body.get("detail") or resp.text or f"HTTP {resp.status_code}"
    except ValueError:
        return resp.text.strip() or f"HTTP {resp.status_code}"


def analyze(metadata: dict, project: Optional[str] = None) -> dict:
    return _post("/api/analyze", {"metadata": metadata, "project": project})


def check(metadata: dict, budgets: dict) -> dict:
    return _post("/api/check", {"metadata": metadata, "budgets": budgets})


def diff(base: dict, head: dict, fail_on: Optional[dict] = None) -> dict:
    return _post("/api/diff", {"base": base, "head": head, "fail_on": fail_on or {}})


def _get(endpoint: str) -> dict:
    key = config.get_api_key()
    if not key:
        raise AuthError(
            "No API key configured. Create one at https://memprobe.dev "
            "(Account -> API keys), then run:  memprobe config set --key <key>"
        )
    url = config.get_server() + endpoint
    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": f"memprobe-cli/{__version__}",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise ApiError(f"Could not reach {url}: {exc}") from exc

    if resp.status_code == 401:
        raise AuthError("API key was rejected. Check it with:  memprobe config show")
    if resp.status_code >= 400:
        raise ApiError(_message(resp))
    try:
        return resp.json()
    except ValueError as exc:
        raise ApiError("The server returned an unexpected (non-JSON) response.") from exc


def account() -> dict:
    return _get("/api/account")
