from __future__ import annotations

import bisect
from pathlib import Path
from typing import Union

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

SCHEMA = "memprobe-lite/1"

_SHF_WRITE = 0x1
_SHF_ALLOC = 0x2
_SHF_EXEC = 0x4


class ExtractError(Exception):
    pass


class _SourceResolver:
    """Address -> compile unit name, via .debug_aranges when present,
    otherwise the low_pc/high_pc range of each CU's top DIE."""

    def __init__(self, elf: ELFFile):
        self._dwarf = None
        self._aranges = None
        self._ranges: list[tuple] = []
        self._names: dict[int, str] = {}
        try:
            if not elf.has_dwarf_info():
                return
            dwarf = elf.get_dwarf_info()
            self._dwarf = dwarf
            self._aranges = dwarf.get_aranges()
            if self._aranges is None:
                self._build_ranges(dwarf)
        except Exception:
            self._dwarf = None
            self._aranges = None

    def _build_ranges(self, dwarf) -> None:
        for cu in dwarf.iter_CUs():
            try:
                attrs = cu.get_top_DIE().attributes
                low = attrs.get("DW_AT_low_pc")
                high = attrs.get("DW_AT_high_pc")
                if low is None or high is None:
                    continue
                start = low.value
                # DW_AT_high_pc is an offset from low_pc in DWARF 4+,
                # an absolute address in older forms.
                end = high.value if high.form == "DW_FORM_addr" else start + high.value
                if end > start:
                    self._ranges.append((start, end, cu.cu_offset))
            except Exception:
                continue
        self._ranges.sort()

    def lookup(self, addr: int) -> Union[str, None]:
        if self._dwarf is None or addr == 0:
            return None
        try:
            offset = self._cu_offset(addr)
            if offset is None and addr & 1:
                # Thumb function addresses carry bit 0 set.
                offset = self._cu_offset(addr & ~1)
            if offset is None:
                return None
            if offset not in self._names:
                self._names[offset] = self._cu_name(offset)
            return self._names[offset] or None
        except Exception:
            return None

    def _cu_offset(self, addr: int):
        if self._aranges is not None:
            return self._aranges.cu_offset_at_addr(addr)
        i = bisect.bisect_right(self._ranges, (addr, float("inf"), 0)) - 1
        if i >= 0:
            start, end, offset = self._ranges[i]
            if start <= addr < end:
                return offset
        return None

    def _cu_name(self, offset: int) -> str:
        cu = self._dwarf.get_CU_at(offset)
        name = cu.get_top_DIE().attributes.get("DW_AT_name")
        if name is None:
            return ""
        value = name.value
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return value.replace("\\", "/")


def extract(path: Union[str, Path]) -> dict:
    path = Path(path)
    if not path.exists():
        raise ExtractError(f"File not found: {path}")
    try:
        with open(path, "rb") as fh:
            return _extract_open(fh, path.name)
    except ExtractError:
        raise
    except Exception as exc:
        raise ExtractError(
            f"Could not read {path.name} as an ELF file: {exc}. "
            f"memprobe analyzes ELF binaries (.elf/.axf)."
        ) from exc


def _unify_file_names(symbols: list) -> None:
    # STT_FILE gives bare basenames, DWARF gives full paths. When a basename
    # matches exactly one known path, use the path so the file isn't counted twice.
    full_paths: dict[str, Union[str, None]] = {}
    for s in symbols:
        f = s.get("file")
        if f and "/" in f:
            base = f.rsplit("/", 1)[1]
            full_paths[base] = None if full_paths.get(base, f) != f else f
    for s in symbols:
        f = s.get("file")
        if f and "/" not in f and full_paths.get(f):
            s["file"] = full_paths[f]


def _extract_open(fh, filename: str) -> dict:
    elf = ELFFile(fh)
    header = elf.header

    binary = {
        "arch": header["e_machine"],
        "bitness": elf.elfclass,
        "endian": "little" if elf.little_endian else "big",
        "entry_point": hex(header["e_entry"]),
        "elf_type": header["e_type"],
    }

    idx_to_name: dict[int, str] = {i: s.name for i, s in enumerate(elf.iter_sections())}

    sections = []
    for sec in elf.iter_sections():
        if sec["sh_type"] == "SHT_NULL":
            continue
        flags = sec["sh_flags"]
        sections.append({
            "name": sec.name,
            "size": sec["sh_size"],
            "addr": sec["sh_addr"],
            "alloc": bool(flags & _SHF_ALLOC),
            "exec": bool(flags & _SHF_EXEC),
            "write": bool(flags & _SHF_WRITE),
            "nobits": sec["sh_type"] == "SHT_NOBITS",
        })

    segments = []
    for seg in elf.iter_segments():
        if seg["p_type"] != "PT_LOAD":
            continue
        fl = seg["p_flags"]
        segments.append({
            "vaddr": hex(seg["p_vaddr"]),
            "paddr": hex(seg["p_paddr"]),
            "filesz": seg["p_filesz"],
            "memsz": seg["p_memsz"],
            "flags": ("r" if fl & 4 else "-") + ("w" if fl & 2 else "-") + ("x" if fl & 1 else "-"),
        })

    symbols = []
    symtab = elf.get_section_by_name(".symtab")
    if isinstance(symtab, SymbolTableSection):
        resolver = _SourceResolver(elf)
        # an STT_FILE entry names the object file for the locals that follow
        # it; globals sit after all locals, so the marker only covers locals
        current_file = None
        for sym in symtab.iter_symbols():
            info = sym["st_info"]
            kind = str(info["type"])
            if kind == "STT_FILE":
                current_file = sym.name or None
                continue
            if sym["st_size"] <= 0:
                continue
            shndx = sym["st_shndx"]
            if not isinstance(shndx, int):
                continue
            bind = str(info["bind"])
            source = resolver.lookup(sym["st_value"])
            if source is None and bind == "STB_LOCAL":
                source = current_file
            entry = {
                "name": sym.name,
                "size": sym["st_size"],
                "addr": sym["st_value"],
                "section": idx_to_name.get(shndx, ""),
                "bind": bind.replace("STB_", ""),
                "kind": kind.replace("STT_", ""),
            }
            if source:
                entry["file"] = source
            symbols.append(entry)
        _unify_file_names(symbols)

    return {
        "schema": SCHEMA,
        "filename": filename,
        "binary": binary,
        "sections": sections,
        "segments": segments,
        "symbols": symbols,
    }
