"""Tests for size parsing, memprobe.toml budget loading, and config storage."""

import pytest

from memprobe_cli.budgets import parse_size, load_budgets, find_config
from memprobe_cli import config


@pytest.mark.parametrize("text,expected", [
    ("512KB", 512 * 1024),
    ("1MB", 1024 * 1024),
    ("1.5 MB", int(1.5 * 1024 * 1024)),
    ("98304", 98304),
    (4096, 4096),
])
def test_parse_size(text, expected):
    assert parse_size(text) == expected


def test_parse_size_invalid():
    with pytest.raises(ValueError):
        parse_size("not-a-size")


def test_load_budgets(tmp_path):
    (tmp_path / "memprobe.toml").write_text(
        '[budgets]\nflash = "512KB"\nram = "128KB"\n".text" = "400KB"\n'
    )
    b = load_budgets(tmp_path)
    assert b["flash"] == 512 * 1024
    assert b["ram"] == 128 * 1024
    assert b[".text"] == 400 * 1024


def test_load_budgets_walks_up(tmp_path):
    (tmp_path / "memprobe.toml").write_text('[budgets]\nflash = "1MB"\n')
    sub = tmp_path / "build" / "out"
    sub.mkdir(parents=True)
    assert find_config(sub) == tmp_path / "memprobe.toml"
    assert load_budgets(sub)["flash"] == 1024 * 1024


def test_load_budgets_none(tmp_path):
    assert load_budgets(tmp_path) == {}


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPROBE_HOME", str(tmp_path))
    monkeypatch.delenv("MEMPROBE_API_KEY", raising=False)
    monkeypatch.delenv("MEMPROBE_SERVER", raising=False)
    config.set_values(api_key="mp_live_abcdef123456", server="https://example.test/")
    assert config.get_api_key() == "mp_live_abcdef123456"
    assert config.get_server() == "https://example.test"  # trailing slash stripped
    assert "…" in config.masked_key()


def test_env_overrides_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPROBE_HOME", str(tmp_path))
    config.set_values(api_key="stored_key")
    monkeypatch.setenv("MEMPROBE_API_KEY", "env_key")
    assert config.get_api_key() == "env_key"


LD_SCRIPT = """
/* STM32H7 memory layout */
MEMORY
{
  FLASH (rx)   : ORIGIN = 0x08000000, LENGTH = 1024K
  FLASH2 (rx)  : ORIGIN = 0x08100000, LENGTH = 0x80000
  RAM_D1 (xrw) : ORIGIN = 0x24000000, LENGTH = 512K
  ITCMRAM (xrw): ORIGIN = 0x00000000, LENGTH = 65536
  WEIRD (r)    : ORIGIN = 0x0, LENGTH = SIZEOF(.text)
}
SECTIONS { }
"""


def test_parse_ld_regions(tmp_path):
    from memprobe_cli.budgets import parse_ld_regions
    p = tmp_path / "app.ld"
    p.write_text(LD_SCRIPT)
    r = parse_ld_regions(p)
    assert r["flash"] == 1024 * 1024 + 0x80000
    assert r["ram"] == 512 * 1024 + 65536


def test_parse_ld_regions_without_memory_block(tmp_path):
    from memprobe_cli.budgets import parse_ld_regions
    p = tmp_path / "bare.ld"
    p.write_text("SECTIONS { .text : { *(.text) } }")
    assert parse_ld_regions(p) == {}


def test_load_watch(tmp_path, monkeypatch):
    from memprobe_cli.budgets import load_watch
    (tmp_path / "memprobe.toml").write_text('[watch]\n"ui_render" = "8KB"\n')
    assert load_watch(tmp_path) == {"ui_render": 8192}


def test_parse_ld_regions_org_len_spelling(tmp_path):
    from memprobe_cli.budgets import parse_ld_regions
    p = tmp_path / "vendor.ld"
    p.write_text(
        "MEMORY\n{\n"
        "  flash (rx) : org = 0x00000000, len = 256K\n"
        "  sram (rwx) : o = 0x20000000, l = 0x10000\n"
        "}\n")
    r = parse_ld_regions(p)
    assert r["flash"] == 256 * 1024
    assert r["ram"] == 0x10000


def test_parse_ld_regions_excludes_eeprom_and_backup(tmp_path):
    from memprobe_cli.budgets import parse_ld_regions
    p = tmp_path / "stm32.ld"
    p.write_text(
        "MEMORY {\n"
        "  FLASH (rx)   : ORIGIN = 0x08000000, LENGTH = 512K\n"
        "  RAM (rw)     : ORIGIN = 0x20000000, LENGTH = 128K\n"
        "  EEPROM (rw)  : ORIGIN = 0x08080000, LENGTH = 4K\n"
        "  BKPSRAM (rw) : ORIGIN = 0x40024000, LENGTH = 4K\n"
        "}\n")
    r = parse_ld_regions(p)
    assert r == {"flash": 512 * 1024, "ram": 128 * 1024}
