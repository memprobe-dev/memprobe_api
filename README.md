<p align="center">
  <img src="https://memprobe.dev/static/logo-256.png" alt="memprobe" width="84">
</p>
<h1 align="center">memprobe</h1>
<p align="center">Firmware memory budgets and size-regression checks for CI, from the command line.</p>

<p align="center">
  <img src="https://memprobe.dev/static/demo-memprobe.gif" alt="memprobe demo" width="760">
</p>

`memprobe` reads the section and symbol table out of your ELF locally and
sends only that metadata to the [memprobe](https://memprobe.dev) API, which
returns the analysis. Only the sizes and symbol names are sent, the same
information `readelf` and `nm` print.

```bash
pip install memprobe
```

## Quick start

1. Create an API key at <https://memprobe.dev> (Account → API keys).
2. Point the CLI at it:

   ```bash
   memprobe config set --key mp_live_xxxxxxxx
   ```

3. Check a build against budgets:

   ```bash
   memprobe init            # writes a memprobe.toml with flash/ram budgets
   memprobe check build/firmware.elf
   ```

   `check` exits non-zero when a budget is exceeded, so it gates a CI job.

## Commands

| Command | What it does |
|---|---|
| `memprobe analyze <elf>` | Size summary: flash/ram totals, biggest sections and symbols. |
| `memprobe check <elf>` | Fail (exit 1) if a budget or watched symbol limit in `memprobe.toml` is exceeded. The CI gate. |
| `memprobe diff <old> <new>` | Size change between two builds, with per-file and per-symbol deltas. `--format markdown` for PR comments. |
| `memprobe diff <elf> --project <name>` | Diff against the project's saved baseline build, no second file needed. |
| `memprobe init` | Scaffold `memprobe.toml` with flash/ram budgets. `--from-ld <script.ld>` fills part capacity from the linker script. |
| `memprobe account` | Show your plan and this month's usage. |
| `memprobe config set --key <key> [--server <url>]` | Store your API key (in `~/.memprobe/config.json`). |
| `memprobe config show` | Show the current key (masked) and server. |

`MEMPROBE_API_KEY` and `MEMPROBE_SERVER` environment variables override the
stored config, which is convenient in CI.

## CI

Because `memprobe check` exits non-zero when a budget is exceeded, it works as a
gate in any CI system. Run it as a build step with `MEMPROBE_API_KEY` set as a
secret:

```bash
pip install memprobe
memprobe check build/firmware.elf
```

On GitHub, [memprobe-action](https://github.com/memprobe-dev/memprobe-action)
wraps this and also posts a size report with symbol-level changes as a PR
comment:

```yaml
- uses: memprobe-dev/memprobe-action@v1
  with:
    file: build/firmware.elf
    api-key: ${{ secrets.MEMPROBE_API_KEY }}
```

## What runs where

| | Local (this tool) | memprobe API |
|---|---|---|
| Reads your ELF | yes | never sees the binary |
| Extracts sections/symbols | yes (via pyelftools) | no |
| Budget / diff / bloat analysis | no | yes |

This package contains no analysis logic and no proprietary code: it's a thin,
open-source client. The deeper analysis (call graph, dead-code, stack usage,
source attribution) lives in the web app at <https://memprobe.dev>.

## License

MIT
