"""Extract commodity memory metadata from an ELF with pyelftools.

This is the only place the CLI touches your binary, and it stays on your
machine. It reads exactly what ``readelf``/``nm`` expose -- the section table,
symbol table, and program headers -- and nothing else. There is no analysis
here; the resulting metadata dict is what gets sent to the memprobe API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

# The wire schema version. Bump when the shape changes so the server can adapt.
SCHEMA = "memprobe-lite/1"

_SHF_WRITE = 0x1
_SHF_ALLOC = 0x2
_SHF_EXEC = 0x4


class ExtractError(Exception):
    """Raised when a file cannot be read as an ELF."""


def extract(path: Union[str, Path]) -> dict:
    """Return a JSON-serialisable metadata dict for the ELF at ``path``.

    Raises :class:`ExtractError` if the file is missing or not an ELF.
    """
    path = Path(path)
    if not path.exists():
        raise ExtractError(f"File not found: {path}")
    try:
        with open(path, "rb") as fh:
            return _extract_open(fh, path.name)
    except ExtractError:
        raise
    except Exception as exc:  # pyelftools raises a variety of types
        raise ExtractError(
            f"Could not read {path.name} as an ELF file: {exc}. "
            f"memprobe analyzes ELF binaries (.elf/.axf)."
        ) from exc


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
        for sym in symtab.iter_symbols():
            if sym["st_size"] <= 0:
                continue
            shndx = sym["st_shndx"]
            if not isinstance(shndx, int):  # SHN_UNDEF / SHN_ABS etc.
                continue
            info = sym["st_info"]
            symbols.append({
                "name": sym.name,
                "size": sym["st_size"],
                "addr": sym["st_value"],
                "section": idx_to_name.get(shndx, ""),
                "bind": str(info["bind"]).replace("STB_", ""),
                "kind": str(info["type"]).replace("STT_", ""),
            })

    return {
        "schema": SCHEMA,
        "filename": filename,
        "binary": binary,
        "sections": sections,
        "segments": segments,
        "symbols": symbols,
    }
