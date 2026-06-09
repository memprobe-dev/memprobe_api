# memprobe

Firmware memory budgets and size-regression checks for CI, from the command line.

`memprobe` reads the section and symbol table out of your ELF **locally** and
sends only that metadata to the [memprobe](https://memprobe.dev) API, which
returns the analysis. **Your binary never leaves your machine** — only the
sizes and symbol names it contains are sent, the same information `readelf` and
`nm` print.

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
| `memprobe check <elf>` | Fail (exit 1) if a budget in `memprobe.toml` is exceeded. The CI gate. |
| `memprobe diff <old> <new>` | Size change between two builds, with per-symbol deltas. `--format markdown` for PR comments. |
| `memprobe init` | Scaffold `memprobe.toml` with flash/ram budgets. |
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

## What runs where

| | Local (this tool) | memprobe API |
|---|---|---|
| Reads your ELF | yes | never sees the binary |
| Extracts sections/symbols | yes (via pyelftools) | — |
| Budget / diff / bloat analysis | — | yes |

This package contains no analysis logic and no proprietary code — it's a thin,
open-source client. The deeper analysis (call graph, dead-code, stack usage,
source attribution) lives in the web app at <https://memprobe.dev>.

## License

MIT
