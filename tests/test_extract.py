"""Tests for local ELF metadata extraction (the only code that reads the binary)."""

from pathlib import Path

import pytest

from memprobe_cli.extract import extract, ExtractError, SCHEMA

FIX = Path(__file__).parent / "fixtures"
ELF = FIX / "sample.elf"


def test_extract_shape():
    meta = extract(ELF)
    assert meta["schema"] == SCHEMA
    assert meta["filename"] == "sample.elf"
    for key in ("binary", "sections", "segments", "symbols"):
        assert key in meta
    b = meta["binary"]
    assert b["arch"].startswith("EM_")
    assert b["bitness"] in (32, 64)
    assert b["endian"] in ("little", "big")
    assert b["entry_point"].startswith("0x")


def test_extract_sections_have_flags():
    secs = extract(ELF)["sections"]
    assert secs, "expected at least one section"
    s = secs[0]
    for key in ("name", "size", "addr", "alloc", "exec", "write", "nobits"):
        assert key in s
    assert isinstance(s["alloc"], bool)


def test_extract_symbols_have_size_and_section():
    syms = extract(ELF)["symbols"]
    assert syms, "expected symbols in a non-stripped ELF"
    assert all(s["size"] > 0 for s in syms)
    assert all("name" in s and "section" in s and "bind" in s for s in syms)


def test_extract_missing_file():
    with pytest.raises(ExtractError):
        extract(FIX / "does_not_exist.elf")


def test_extract_non_elf(tmp_path):
    junk = tmp_path / "notelf.bin"
    junk.write_bytes(b"this is not an elf file")
    with pytest.raises(ExtractError):
        extract(junk)
