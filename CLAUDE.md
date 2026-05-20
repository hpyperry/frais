# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CheckUpgrade is a macOS BYOK CLI that scans installed Applications and Homebrew packages for available updates. It uses an OpenAI-compatible LLM (user-supplied key) with a structured 3-step research pipeline for finding latest versions and generating update advice.

## Commands

```bash
# Development setup
uv sync --extra dev

# Run the CLI
uv run checkupgrade doctor
uv run checkupgrade advise
uv run checkupgrade advise --apps-only
uv run checkupgrade advise -j 5

# Run all tests
uv run pytest

# Run a single test file or test
uv run pytest tests/test_cli.py
uv run pytest tests/test_cli.py::test_explicit_plugins_skip_applications

# Build macOS binary (requires pyinstaller)
uv run --extra build python scripts/build_binary.py
```

## Architecture

```
src/checkupgrade/
  cli.py              Typer app: doctor, advise, update, config, plugins, ignore
  models.py           Dataclasses: SystemProfile, SoftwareItem, UpdateCandidate, ScanResult
  config.py           BYOK config: reads ~/.config/checkupgrade/config.toml, env var overrides
  ignore.py           Ignore list: load/save/add/remove ignored app IDs (~/.config/checkupgrade/ignore.txt)
  agent.py            AgentClient — structured 3-step research pipeline (generate queries, pick URLs, extract version)
  tools.py            Web tools: web_search (DDGS), web_fetch, web_fetch_batch (internal, not LLM-exposed)
  research.py         Orchestrates version research with iTunes fast path + LLM structured pipeline
  version_checker.py  Fast version checks: iTunes API, GitHub API
  system.py           macOS detection
  scanners/
    applications.py    Scans /Applications and ~/Applications for .app bundles via Info.plist
  plugins/
    __init__.py        Re-exports ScannerPlugin as public API
    base.py            ScannerPlugin ABC (is_available, scan)
    registry.py        Plugin registry; discovers built-in + third-party plugins via entry points
    homebrew/          HomebrewPlugin — runs brew outdated --json=v2, brew info, brew uses
    npm/               NpmPlugin — runs npm outdated -g --json for global packages
```

## Concurrency model

Three layers of concurrency:

1. **Scan layer**: applications scanner and all enabled plugins run in parallel via a single `ThreadPoolExecutor`. No data dependency between them (applications write `result.applications`, plugins write `result.candidates`).
2. **Research layer**: each app is researched concurrently (controlled by `-j`, default 10)
3. **Summary layer**: AI summaries for each candidate are generated concurrently

## Research flow

Each non-App Store app goes through a structured 3-step pipeline:

1. **Generate queries**: LLM produces 2-3 search queries for the app. We execute all queries via `web_search` in parallel.
2. **Pick URLs**: LLM analyzes deduplicated search results and picks the top 3 most promising URLs.
3. **Extract version**: We fetch all 3 URLs via `web_fetch_batch`. LLM parses the content and returns version info.

App Store apps skip this entirely — they use the iTunes API directly (~1s).

## Data flow

**`advise` command**:
1. `run_scan()` — detect system, scan applications and plugins in parallel; accepts optional `progress`/`task_id` for live progress updates
2. Filter ignored apps (from `~/.config/checkupgrade/ignore.txt`)
3. Research with progress bar — iTunes fast path for App Store apps, 3-step LLM pipeline for others
4. Summarize with progress bar — generate Chinese-language summaries via LLM

## Key patterns

- **BYOK model**: LLM config merges env vars (`CHECKUPGRADE_LLM_*`) over file values. `require_raw_llm_config()` raises `ValueError` listing missing keys. API keys are never logged or printed in full.
- **Testing**: Uses `monkeypatch` (pytest fixture) for all external dependencies — subprocess, filesystem, env vars. No mock library. Test data for apps uses `tmp_path` with real plistlib dumps.
- **Version comparison**: Uses `packaging.version.Version`; strips leading `v`/`V` before comparing.
- **Source classification**: Applications are classified as APP_STORE, LOCAL_BUILD, NETWORK_DOWNLOAD, APPLICATION, or UNKNOWN based on codesign authority, team ID, and quarantine xattr presence.
- **Structured LLM pipeline**: Agent does NOT use tool calling. Instead, 3 discrete LLM calls per app: generate queries, pick URLs, extract version. Each call returns JSON.
- **Logging**: `--verbose` sets INFO, `--debug` sets DEBUG. Logs go to stderr and `~/.local/state/checkupgrade/checkupgrade.log` by default. `--log-file` overrides path, `--no-log` disables file logging. Auto-truncates at 5MB.
- **Progress bar**: `rich.progress.Progress` shows scan/research/summarize phases with elapsed time. Scan total is dynamic: 1 (applications) + N (enabled plugins), or N for `--plugins`, or 1 for `--apps-only`.
- **Ignore list**: `~/.config/checkupgrade/ignore.txt` stores app IDs to skip during `advise`. Managed via `checkupgrade ignore add/remove/list`. Filtered after scan, before research.
- **Plugin discovery**: `registry.py` uses `importlib.metadata.entry_points(group="checkupgrade.plugins")` to discover third-party plugins at runtime. Built-in plugins (Homebrew) are always present. Failed loads are logged, not fatal.
