"""Read budgets from a ``memprobe.toml`` and parse human size strings.

The CLI resolves budgets locally and sends them to the API with a check; the
server is the source of truth for whether they pass. Kept tiny and dependency-
light (tomllib on 3.11+, tomli before that).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - exercised on <3.11
    import tomli as _toml  # type: ignore[no-redef]


_SIZE_RE = re.compile(r"^\s*([\d.]+)\s*([kKmMgG]?)(?:i?[bB])?\s*$")
_MULT = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}


def parse_size(s) -> int:
    """Parse ``"512KB"`` / ``"1.5 MB"`` / ``98304`` into bytes."""
    if isinstance(s, (int, float)):
        return int(s)
    m = _SIZE_RE.match(str(s))
    if not m:
        raise ValueError(f"Invalid size: {s!r} (try e.g. 512KB, 1MB, 98304)")
    return int(float(m.group(1)) * _MULT[m.group(2).lower()])


def load_budgets(start: Optional[Path] = None) -> dict:
    """Find the nearest ``memprobe.toml`` (cwd upward) and return its parsed
    ``[budgets]`` table as a name -> bytes dict. Empty when none is found."""
    path = find_config(start)
    if path is None:
        return {}
    try:
        with open(path, "rb") as fh:
            data = _toml.load(fh)
    except (OSError, _toml.TOMLDecodeError):
        return {}
    raw = data.get("budgets", {})
    out: dict = {}
    for key, val in raw.items():
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
