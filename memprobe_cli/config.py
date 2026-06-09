"""Persistent CLI config: API key and server URL."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

DEFAULT_SERVER = "https://memprobe.dev"


def _home() -> Path:
    base = os.environ.get("MEMPROBE_HOME")
    p = Path(base) if base else Path.home() / ".memprobe"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path() -> Path:
    return _home() / "config.json"


def load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(cfg: dict) -> Path:
    p = _path()
    p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def set_values(*, api_key: Optional[str] = None, server: Optional[str] = None) -> Path:
    cfg = load()
    if api_key is not None:
        cfg["api_key"] = api_key.strip()
    if server is not None:
        cfg["server"] = server.strip().rstrip("/")
    return save(cfg)


def get_api_key() -> Optional[str]:
    return os.environ.get("MEMPROBE_API_KEY") or load().get("api_key")


def get_server() -> str:
    return (os.environ.get("MEMPROBE_SERVER") or load().get("server") or DEFAULT_SERVER).rstrip("/")


def masked_key() -> str:
    key = get_api_key()
    if not key:
        return "(not set)"
    return f"{key[:8]}…{key[-4:]}" if len(key) > 14 else "(set)"
