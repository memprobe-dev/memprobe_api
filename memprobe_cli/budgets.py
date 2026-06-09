"""Read budgets from a memprobe.toml and parse human size strings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

try:
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover
    import tomli as _toml  # type: ignore[no-redef]


_SIZE_RE = re.compile(r"^\s*([\d.]+)\s*([kKmMgG]?)(?:i?[bB])?\s*$")
_MULT = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}


def parse_size(s) -> int:
    if isinstance(s, (int, float)):
        return int(s)
    m = _SIZE_RE.match(str(s))
    if not m:
        raise ValueError(f"Invalid size: {s!r} (try 512KB, 1MB, or 98304)")
    return int(float(m.group(1)) * _MULT[m.group(2).lower()])


def load_budgets(start: Optional[Path] = None) -> dict:
    path = find_config(start)
    if path is None:
        return {}
    try:
        with open(path, "rb") as fh:
            data = _toml.load(fh)
    except (OSError, _toml.TOMLDecodeError):
        return {}
    out: dict = {}
    for key, val in data.get("budgets", {}).items():
        try:
            out[key] = parse_size(val)
        except ValueError:
            continue
    return out


def find_config(start: Optional[Path] = None) -> Optional[Path]:
    cur = (start or Path.cwd()).resolve()
    for d in (cur, *cur.parents):
        candidate = d / "memprobe.toml"
        if candidate.is_file():
            return candidate
    return None
