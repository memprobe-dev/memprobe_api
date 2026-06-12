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


def _load_table(table: str, start: Optional[Path] = None) -> dict:
    path = find_config(start)
    if path is None:
        return {}
    try:
        with open(path, "rb") as fh:
            data = _toml.load(fh)
    except (OSError, _toml.TOMLDecodeError):
        return {}
    out: dict = {}
    for key, val in data.get(table, {}).items():
        try:
            out[key] = parse_size(val)
        except ValueError:
            continue
    return out


def load_budgets(start: Optional[Path] = None) -> dict:
    return _load_table("budgets", start)


def load_regions(start: Optional[Path] = None) -> dict:
    return _load_table("regions", start)


def load_watch(start: Optional[Path] = None) -> dict:
    return _load_table("watch", start)


_LD_MEMORY_RE = re.compile(r"\bMEMORY\b[^{]*\{(.*?)\}", re.DOTALL)
# ld accepts ORIGIN/org/o and LENGTH/len/l
_LD_REGION_RE = re.compile(
    r"^\s*(\w+)\s*(?:\([^)]*\))?\s*:\s*(?:ORIGIN|org|o)\s*=\s*[^,]+,\s*(?:LENGTH|len|l)\s*=\s*([0-9xXa-fA-F]+[kKmM]?)\s*$",
    re.MULTILINE | re.IGNORECASE)
_FLASH_NAMES = ("FLASH", "ROM", "AXIROM", "QSPI", "OSPI")
_RAM_NAMES = ("RAM", "SRAM", "DTCM", "ITCM", "CCM", "TCM", "HEAP", "DRAM", "IRAM")


def _ld_length(value: str) -> Optional[int]:
    value = value.strip()
    mult = 1
    if value[-1:] in "kK":
        mult, value = 1024, value[:-1]
    elif value[-1:] in "mM":
        mult, value = 1024 ** 2, value[:-1]
    try:
        return int(value, 0) * mult
    except ValueError:
        return None


def parse_ld_regions(path: Path) -> dict:
    # only plain LENGTH literals; expressions are skipped so the caller
    # falls back to manual entry
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    block = _LD_MEMORY_RE.search(text)
    if not block:
        return {}
    out = {"flash": 0, "ram": 0}
    for name, length in _LD_REGION_RE.findall(block.group(1)):
        size = _ld_length(length)
        if size is None:
            continue
        upper = name.upper()
        if any(k in upper for k in _FLASH_NAMES):
            out["flash"] += size
        elif any(k in upper for k in _RAM_NAMES):
            out["ram"] += size
    return {k: v for k, v in out.items() if v > 0}


def find_config(start: Optional[Path] = None) -> Optional[Path]:
    cur = (start or Path.cwd()).resolve()
    for d in (cur, *cur.parents):
        candidate = d / "memprobe.toml"
        if candidate.is_file():
            return candidate
    return None
