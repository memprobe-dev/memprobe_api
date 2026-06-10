"""CLI tests with the API client mocked, so nothing hits the network."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from memprobe_cli import cli as cli_mod
from memprobe_cli.cli import cli, parse_fail_on

FIX = Path(__file__).parent / "fixtures"
ELF = FIX / "sample.elf"


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPROBE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MEMPROBE_API_KEY", "mp_live_testkey")  # so client has a key


def _run(*args):
    return CliRunner().invoke(cli, list(args))


# -- config --------------------------------------------------------------------

def test_config_set_and_show(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMPROBE_API_KEY", raising=False)
    r = _run("config", "set", "--key", "mp_live_abcdefgh1234")
    assert r.exit_code == 0, r.output
    r2 = _run("config", "show")
    assert "mp_live_" in r2.output and "1234" in r2.output


# -- analyze -------------------------------------------------------------------

def test_analyze(monkeypatch):
    captured = {}

    def fake_analyze(meta, project=None):
        captured["meta"] = meta
        captured["project"] = project
        return {
            "filename": "sample.elf", "total_flash": 2048, "total_ram": 512,
            "section_count": 4, "symbol_count": 3,
            "top_symbols": [{"name": "main", "size": 200, "section": ".text"}],
            "warnings": [{"level": "warning", "message": "big stack"}],
        }

    monkeypatch.setattr(cli_mod.client, "analyze", fake_analyze)
    r = _run("analyze", str(ELF), "--project", "demo")
    assert r.exit_code == 0, r.output
    assert "main" in r.output and "2.0 KB" in r.output
    # the binary was extracted locally and only metadata was passed on
    assert captured["meta"]["schema"].startswith("memprobe-lite/")
    assert captured["project"] == "demo"


def test_analyze_json(monkeypatch):
    monkeypatch.setattr(cli_mod.client, "analyze",
                        lambda m, p=None: {"total_flash": 10, "total_ram": 0})
    r = _run("analyze", str(ELF), "--json")
    assert r.exit_code == 0
    assert json.loads(r.output)["total_flash"] == 10


# -- check (the CI gate) -------------------------------------------------------

def test_check_pass(monkeypatch):
    monkeypatch.setattr(cli_mod.client, "check",
                        lambda m, b: {"passed": True, "total_flash": 100, "total_ram": 50,
                                      "violations": []})
    r = _run("check", str(ELF), "--budget-flash", "1MB")
    assert r.exit_code == 0, r.output
    assert "All budgets OK" in r.output


def test_check_fail_exits_nonzero(monkeypatch):
    monkeypatch.setattr(cli_mod.client, "check",
                        lambda m, b: {"passed": False, "total_flash": 9000, "total_ram": 50,
                                      "violations": [{"kind": "flash", "label": "Flash",
                                                      "budget": 1024, "actual": 9000, "overage": 7976}]})
    r = _run("check", str(ELF), "--budget-flash", "1KB")
    assert r.exit_code == 1
    assert "over budget" in r.output


def test_check_no_budget(monkeypatch):
    r = _run("check", str(ELF))  # no memprobe.toml, no overrides
    assert r.exit_code == 1
    assert "No budgets" in r.output


# -- diff ----------------------------------------------------------------------

def test_diff_markdown(monkeypatch):
    monkeypatch.setattr(cli_mod.client, "diff",
                        lambda base, head, fail_on=None: {
                            "flash_delta": 1200, "ram_delta": -64,
                            "symbol_diffs": [{"name": "foo", "old_size": 100, "new_size": 1300, "delta": 1200}],
                            "passed": True, "regressions": []})
    r = _run("diff", str(ELF), str(ELF), "--format", "markdown")
    assert r.exit_code == 0, r.output
    assert "memprobe firmware size report" in r.output
    assert "`foo`" in r.output


def test_diff_project_baseline(monkeypatch):
    seen = {}

    def fake_diff_project(head, project, fail_on=None):
        seen["project"] = project
        return {"flash_delta": 256, "ram_delta": 0, "symbol_diffs": [],
                "passed": True, "regressions": [],
                "base_build_id": 12, "base_filename": "firmware-v1.elf"}

    monkeypatch.setattr(cli_mod.client, "diff_project", fake_diff_project)
    r = _run("diff", str(ELF), "--project", "demo", "--format", "markdown")
    assert r.exit_code == 0, r.output
    assert seen["project"] == "demo"
    assert "firmware-v1.elf" in r.output


def test_diff_one_file_without_project_errors():
    r = _run("diff", str(ELF))
    assert r.exit_code == 1
    assert "--project" in r.output


def test_diff_fail_on(monkeypatch):
    monkeypatch.setattr(cli_mod.client, "diff",
                        lambda base, head, fail_on=None: {
                            "flash_delta": 5000, "ram_delta": 0, "symbol_diffs": [],
                            "passed": False, "regressions": [{"metric": "flash", "delta": 5000, "limit": 1024}]})
    r = _run("diff", str(ELF), str(ELF), "--json", "--fail-on", "flash:1KB")
    assert r.exit_code == 1
    assert json.loads(r.output)["regressions"][0]["metric"] == "flash"


# -- init + parse_fail_on ------------------------------------------------------

def test_init_scaffold():
    runner = CliRunner()
    with runner.isolated_filesystem():
        r = runner.invoke(cli, ["init"])
        assert r.exit_code == 0, r.output
        assert "[budgets]" in Path("memprobe.toml").read_text()


def test_parse_fail_on():
    assert parse_fail_on("flash:+2KB,ram:512") == {"flash": 2048, "ram": 512}
    assert parse_fail_on("") == {}


# -- auth error surfaces cleanly ----------------------------------------------

def test_missing_key_is_a_clean_error(monkeypatch):
    monkeypatch.delenv("MEMPROBE_API_KEY", raising=False)
    # No key configured anywhere -> the client raises AuthError, CLI exits 1.
    r = _run("analyze", str(ELF))
    assert r.exit_code == 1
    assert "API key" in r.output
