# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CheckUpgrade is a macOS BYOK CLI that scans installed Applications and Homebrew packages for available updates. It uses an OpenAI-compatible LLM (user-supplied key) with tool calling for researching application release versions and generating update advice.

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
  cli.py              Typer app: doctor, advise, update, config, plugins
  models.py           Dataclasses: SystemProfile, SoftwareItem, UpdateCandidate, ScanResult
  config.py           BYOK config: reads ~/.config/checkupgrade/config.toml, env var overrides
  agent.py            AgentClient — OpenAI-compatible chat completions with tool calling
  tools.py            LLM tools: web_search (DDGS), web_fetch, web_fetch_batch
  research.py         Orchestrates version research with three-tier fast/slow paths
  version_checker.py  Fast version checks: iTunes API, GitHub API
  system.py           macOS detection
  scanners/
    applications.py    Scans /Applications and ~/Applications for .app bundles via Info.plist
  plugins/
    base.py            ScannerPlugin ABC (is_available, scan)
    registry.py        Plugin registry; HomebrewPlugin is the only v1 plugin
    homebrew.py        HomebrewPlugin — runs brew outdated --json=v2, brew info, brew uses
```

## Concurrency model

Three layers of concurrency:

1. **Plugin layer**: all plugins run in parallel via `ThreadPoolExecutor`
2. **Research layer**: each app is researched concurrently (controlled by `-j`, default 10)
3. **Summary layer**: AI summaries for each candidate are generated concurrently

Per-app research uses a three-tier path:
- **Fast 1 — iTunes API** (~1s): App Store apps only, queries `itunes.apple.com/lookup`
- **Fast 2 — GitHub API** (~3s): web search → extract GitHub repo → `releases/latest` API
- **Slow — LLM tool calling** (~20s): LLM uses `web_search` + `web_fetch_batch` tools

GitHub fast path and LLM run concurrently; if GitHub returns first, LLM is abandoned.

## Data flow

**`advise` command**:
1. `run_scan()` — detect system, scan applications, run plugins concurrently
2. `_research_apps_concurrent()` — for each app (App Store → iTunes, others → GitHub + LLM concurrent)
3. `_summarize_concurrent()` — generate Chinese-language summaries via LLM

## Key patterns

- **BYOK model**: LLM config merges env vars (`CHECKUPGRADE_LLM_*`) over file values. `require_raw_llm_config()` raises `ValueError` listing missing keys. API keys are never logged or printed in full.
- **Testing**: Uses `monkeypatch` (pytest fixture) for all external dependencies — subprocess, filesystem, env vars. No mock library. Test data for apps uses `tmp_path` with real plistlib dumps.
- **Version comparison**: Uses `packaging.version.Version`; strips leading `v`/`V` before comparing.
- **Source classification**: Applications are classified as APP_STORE, LOCAL_BUILD, NETWORK_DOWNLOAD, APPLICATION, or UNKNOWN based on codesign authority, team ID, and quarantine xattr presence.
- **LLM tool calling**: Agent receives `web_search` and `web_fetch_batch` tools. System prompt constrains to max 2 tool calls per round, max 4 rounds total.
- **Version tag filtering**: `_is_version_tag()` rejects non-version tags like `svn-trunk`, `ubuntu24/xxx`, `nightly`.
- **GitHub repo matching**: `find_github_repo_from_search()` prefers repos whose name matches the app name.
- **Logging**: `--verbose` sets INFO, `--debug` sets DEBUG. Logs go to stderr; `--log-file` adds a file handler. httpx logging is clamped to INFO unless `--debug`.
