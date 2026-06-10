from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich import box

from . import __version__, client, config
from .budgets import load_budgets, load_regions, parse_size
from .extract import extract, ExtractError

console = Console(highlight=False)
err = Console(stderr=True, highlight=False)


def _die(message: str) -> None:
    err.print(f"[bold red]Error:[/] {message}")
    sys.exit(1)


def _extract_or_die(path: str) -> dict:
    try:
        return extract(Path(path))
    except ExtractError as exc:
        _die(str(exc))


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (client.AuthError, client.QuotaError, client.ApiError) as exc:
        _die(str(exc))


def _human(n: int) -> str:
    neg = "-" if n < 0 else ""
    n = abs(n)
    if n < 1024:
        return f"{neg}{n} B"
    if n < 1024 * 1024:
        return f"{neg}{n / 1024:.1f} KB"
    return f"{neg}{n / 1024 / 1024:.2f} MB"


def _signed(n: int) -> str:
    return _human(n) if n < 0 else f"+{_human(n)}"


def _short_path(path: str, parts: int = 3) -> str:
    pieces = path.replace("\\", "/").split("/")
    return "/".join(pieces[-parts:]) if len(pieces) > parts else path


def _usage(used: int, capacity: Optional[int]) -> str:
    if not capacity:
        return f"[bold]{_human(used)}[/]"
    pct = used / capacity * 100
    color = "red" if pct >= 90 else "yellow" if pct >= 75 else "green"
    return f"[bold]{_human(used)}[/] / {_human(capacity)} [{color}]({pct:.1f}%)[/]"


def parse_fail_on(spec: str) -> dict:
    limits: dict = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise click.BadParameter(f"expected metric:size, got '{part}'")
        metric, size = part.split(":", 1)
        metric = metric.strip().lower()
        if metric not in ("flash", "ram"):
            raise click.BadParameter(f"unknown metric '{metric}' (use 'flash' or 'ram')")
        limits[metric] = parse_size(size.strip().lstrip("+"))
    return limits


_MEMPROBE_TOML = """\
# memprobe.toml
# `memprobe check <firmware.elf>` exits non-zero when a budget is exceeded.

[budgets]
flash = "512KB"
ram   = "128KB"

# Per-section budgets (optional):
# ".text" = "400KB"
# ".bss"  = "96KB"

# Physical part capacity. Adds utilization percentages to analyze and check.
# [regions]
# flash = "1MB"
# ram   = "320KB"
"""


@click.group()
@click.version_option(__version__, prog_name="memprobe")
def cli() -> None:
    """Firmware memory budgets and size checks. Your binary stays local."""


@cli.group(name="config")
def config_cmd() -> None:
    """Manage your API key and server URL."""


@config_cmd.command("set")
@click.option("--key", "api_key", default=None, help="API key from https://memprobe.dev.")
@click.option("--server", default=None, help="API server URL (defaults to https://memprobe.dev).")
def config_set(api_key: Optional[str], server: Optional[str]) -> None:
    """Store your API key and/or server URL."""
    if api_key is None and server is None:
        _die("Nothing to set. Pass --key and/or --server.")
    path = config.set_values(api_key=api_key, server=server)
    console.print(f"  [green]✓[/] saved to {path}")
    console.print(f"  key: [cyan]{config.masked_key()}[/]   server: [cyan]{config.get_server()}[/]")


@config_cmd.command("show")
def config_show() -> None:
    """Show the current configuration."""
    console.print(f"  key:    [cyan]{config.masked_key()}[/]")
    console.print(f"  server: [cyan]{config.get_server()}[/]")
    if os.environ.get("MEMPROBE_API_KEY"):
        console.print("  [dim](key is coming from $MEMPROBE_API_KEY)[/]")


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output JSON instead of a table.")
def account(as_json: bool) -> None:
    """Show your plan and this month's usage."""
    data = _call(client.account)

    if as_json:
        click.echo(json.dumps(data, indent=2))
        return

    a = data.get("analyses", {})
    used = a.get("used", 0)
    limit = a.get("limit")
    quota = f"{used}" if limit is None else f"{used} / {limit}"
    suffix = " (unlimited)" if limit is None else ""

    console.print()
    console.print(f"  Plan      [bold]{data.get('plan', 'free').upper()}[/]")
    console.print(f"  Analyses  [bold]{quota}[/]{suffix}  [dim]this month[/]")
    b = data.get("builds", {})
    p = data.get("projects", {})
    console.print(f"  Builds    {b.get('used', 0)} / {b.get('limit', '-')}")
    console.print(f"  Projects  {p.get('used', 0)} / {p.get('limit', '-')}")
    if a.get("resets"):
        console.print(f"  [dim]Resets {a.get('resets')}[/]")
    console.print()


@cli.command()
@click.argument("file", type=click.Path(exists=False))
@click.option("--json", "as_json", is_flag=True, help="Output JSON instead of a table.")
@click.option("--project", default=None, help="Save this build under a project name.")
@click.option("--top", type=int, default=10, show_default=True, help="How many top symbols to show.")
def analyze(file: str, as_json: bool, project: Optional[str], top: int) -> None:
    """Size summary for an ELF (flash/ram totals, biggest sections and symbols)."""
    meta = _extract_or_die(file)
    result = _call(client.analyze, meta, project)

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    regions = load_regions(Path(file).resolve().parent)
    console.rule(f"[bold]memprobe: {result.get('filename', Path(file).name)}[/]")
    console.print()
    console.print(f"  Flash  {_usage(result.get('total_flash', 0), regions.get('flash'))}")
    console.print(f"  RAM    {_usage(result.get('total_ram', 0), regions.get('ram'))}")
    console.print(f"  [dim]{result.get('section_count', 0)} sections, "
                  f"{result.get('symbol_count', 0)} symbols[/]")

    syms = result.get("top_symbols") or []
    if syms:
        console.print()
        t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold dim")
        t.add_column("Symbol", style="cyan")
        t.add_column("Size", justify="right")
        t.add_column("Section", style="dim")
        for s in syms[:top]:
            t.add_row(s.get("name", ""), _human(s.get("size", 0)), s.get("section", ""))
        console.print(t)

    files = result.get("top_files") or []
    if files:
        t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold dim")
        t.add_column("Source file", style="cyan")
        t.add_column("Flash", justify="right")
        t.add_column("RAM", justify="right")
        for f in files[:top]:
            t.add_row(_short_path(f.get("file", "")),
                      _human(f.get("flash", 0)), _human(f.get("ram", 0)))
        console.print(t)

    for w in result.get("warnings", []):
        tag = "yellow" if w.get("level") == "warning" else "dim"
        console.print(f"  [{tag}]• {w.get('message', '')}[/]")
    console.print()


@cli.command()
@click.argument("file", type=click.Path(exists=False))
@click.option("--budget-flash", default=None, help="Max flash, such as 512KB. Overrides memprobe.toml.")
@click.option("--budget-ram", default=None, help="Max RAM, such as 128KB. Overrides memprobe.toml.")
@click.option("--json", "as_json", is_flag=True, help="Output the result as JSON.")
def check(file: str, budget_flash: Optional[str], budget_ram: Optional[str], as_json: bool) -> None:
    """Fail (exit 1) if a budget is exceeded. The CI gate.

    Budgets come from the nearest memprobe.toml; --budget-flash/--budget-ram
    override them.
    """
    meta = _extract_or_die(file)
    budgets = load_budgets(Path(file).resolve().parent)
    if budget_flash:
        budgets["flash"] = parse_size(budget_flash)
    if budget_ram:
        budgets["ram"] = parse_size(budget_ram)
    if not budgets:
        _die("No budgets configured. Run 'memprobe init' or pass --budget-flash / --budget-ram.")

    result = _call(client.check, meta, budgets)
    violations = result.get("violations", [])
    passed = result.get("passed", not violations)

    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        regions = load_regions(Path(file).resolve().parent)
        console.print(f"  Flash  {_usage(result.get('total_flash', 0), regions.get('flash'))}")
        console.print(f"  RAM    {_usage(result.get('total_ram', 0), regions.get('ram'))}")
        for v in violations:
            err.print(f"  [bold red]✗ {v.get('label', v.get('kind'))} over budget by "
                      f"{_human(v.get('overage', 0))} "
                      f"({_human(v.get('actual', 0))} > {_human(v.get('budget', 0))})[/]")
        if passed:
            console.print("  [green]✓ All budgets OK[/]")

    sys.exit(1 if not passed else 0)


@cli.command()
@click.argument("old_file", type=click.Path(exists=False))
@click.argument("new_file", type=click.Path(exists=False), required=False)
@click.option("--project", default=None,
              help="Diff one file against this project's baseline (or newest) saved build.")
@click.option("--json", "as_json", is_flag=True, help="Output the diff as JSON.")
@click.option("--format", "fmt", type=click.Choice(["terminal", "markdown"]), default="terminal",
              help="'markdown' is ready to post as a PR comment.")
@click.option("--fail-on", "fail_on", default=None,
              help="Fail if a metric grows beyond a limit, like 'flash:+2KB,ram:512'.")
@click.option("--top", type=int, default=15, show_default=True, help="How many symbol changes to show.")
def diff(old_file: str, new_file: Optional[str], project: Optional[str],
         as_json: bool, fmt: str, fail_on: Optional[str], top: int) -> None:
    """Size change between two builds, with per-symbol deltas.

    Pass two files, or one file with --project to diff against the build
    saved on the server (run diff before analyze so the comparison is not
    against the build you are about to save).
    """
    limits = parse_fail_on(fail_on) if fail_on else {}
    if new_file is None:
        if not project:
            _die("Pass two files, or one file with --project.")
        head = _extract_or_die(old_file)
        result = _call(client.diff_project, head, project, limits)
        old_name = result.get("base_filename") or f"{project} (saved build)"
        new_name = Path(old_file).name
    else:
        base = _extract_or_die(old_file)
        head = _extract_or_die(new_file)
        result = _call(client.diff, base, head, limits)
        old_name = Path(old_file).name
        new_name = Path(new_file).name

    flash_d = result.get("flash_delta", 0)
    ram_d = result.get("ram_delta", 0)
    diffs = result.get("symbol_diffs", [])
    regressions = result.get("regressions", [])
    passed = result.get("passed", not regressions)

    if as_json:
        click.echo(json.dumps(result, indent=2))
        sys.exit(1 if not passed else 0)

    if fmt == "markdown":
        md = _render_diff_markdown(old_name, new_name, flash_d, ram_d, diffs, top)
        click.echo(md)
        sys.exit(1 if not passed else 0)

    console.rule(f"[bold]memprobe diff: {old_name} -> {new_name}[/]")
    console.print()
    console.print(f"  Flash  [{'red' if flash_d > 0 else 'green'}]{_signed(flash_d)}[/]")
    console.print(f"  RAM    [{'red' if ram_d > 0 else 'green'}]{_signed(ram_d)}[/]")
    if diffs:
        console.print()
        t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold dim")
        t.add_column("Symbol", style="cyan")
        t.add_column("Old", justify="right")
        t.add_column("New", justify="right")
        t.add_column("Delta", justify="right")
        for s in diffs[:top]:
            d = s.get("delta", 0)
            t.add_row(s.get("name", ""), str(s.get("old_size", 0) or "-"),
                      str(s.get("new_size", 0) or "-"),
                      f"[{'red' if d > 0 else 'green'}]{_signed(d)}[/]")
        console.print(t)
    console.print()
    if not passed:
        for r in regressions:
            err.print(f"  [bold red]✗ {r.get('metric', '').upper()} grew "
                      f"{_human(r.get('delta', 0))} (limit +{_human(r.get('limit', 0))})[/]")
        sys.exit(1)


@cli.command()
@click.option("--force", is_flag=True, help="Overwrite existing files.")
def init(force: bool) -> None:
    """Scaffold a memprobe.toml with flash/RAM budgets."""
    def _write(target: Path, content: str) -> None:
        if target.exists() and not force:
            err.print(f"  [yellow]{target} already exists[/] (use --force to overwrite).")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        console.print(f"  [green]✓[/] wrote {target}")

    _write(Path("memprobe.toml"), _MEMPROBE_TOML)
    console.print()
    console.print("  Next: set your key with [cyan]memprobe config set --key <key>[/], "
                  "then [cyan]memprobe check <firmware.elf>[/].")


def _render_diff_markdown(old_name: str, new_name: str, flash_d: int, ram_d: int,
                          diffs: list, top: int) -> str:
    def sign(n):
        return f"+{n:,}" if n >= 0 else f"{n:,}"
    lines = [
        "### memprobe firmware size report",
        "",
        f"`{old_name}` → `{new_name}`",
        "",
        "| Metric | Change |",
        "|---|---:|",
        f"| Flash | {sign(flash_d)} B |",
        f"| RAM | {sign(ram_d)} B |",
    ]
    changed = [s for s in diffs if s.get("delta")]
    if changed:
        lines += ["", "<details><summary>Top symbol changes</summary>", "",
                  "| Symbol | Old | New | Change |", "|---|---:|---:|---:|"]
        for s in changed[:top]:
            lines.append(f"| `{s.get('name','')}` | {s.get('old_size',0):,} | "
                         f"{s.get('new_size',0):,} | {sign(s.get('delta',0))} |")
        lines.append("</details>")
    return "\n".join(lines)


if __name__ == "__main__":
    cli()
