# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Task workflow (mandatory)

For every task the user gives, follow these steps in order:

1. **Enter plan mode** — do not write code before planning is approved.
2. **Research** — read CLAUDE.md and README.md, analyze recent git log for context.
3. **Impact analysis** — evaluate the task's impact on the full codebase.
4. **Write plan** — list detailed changes, files to touch, and implementation approach.
5. **Test coverage** — review existing tests and add new ones to cover all changed paths.
6. **Build binary** — run `uv run --extra build python scripts/build_binary.py` and verify with the built artifact.
7. **Update docs** — update CLAUDE.md and README.md to reflect the changes.

## Project overview

CheckUpgrade is a macOS BYOK CLI that scans installed Applications, Homebrew packages, and npm global packages for available updates. It uses an OpenAI-compatible LLM (user-supplied key) with a structured 3-step research pipeline for finding latest versions and generating update advice.

All scanning is plugin-based — the built-in `applications`, `homebrew`, and `npm` scanners are all `ScannerPlugin` implementations.

## Commands

```bash
# Development setup
uv sync --extra dev

# Run the CLI
uv run checkupgrade doctor
uv run checkupgrade advise
uv run checkupgrade advise --all
uv run checkupgrade advise --apps-only
uv run checkupgrade advise -j 5

# Run all tests
uv run pytest

# Run a single test file or test
uv run pytest tests/test_cli.py
uv run pytest tests/test_homebrew.py

# Build macOS binary (requires pyinstaller)
uv run --extra build python scripts/build_binary.py
```

## Architecture

```
src/checkupgrade/
  cli.py              Typer app: doctor, advise, update, config, plugins, ignore
  models.py           Dataclasses: SystemProfile, SoftwareItem, UpdateCandidate,
                      PluginScanResult, ScanResult, ResearchResult, etc.
  config.py           BYOK config: reads ~/.config/checkupgrade/config.toml, env var overrides
  ignore.py           Ignore list: load/save/add/remove ignored app IDs (~/.config/checkupgrade/ignore.txt)
  agent.py            AgentClient — structured 3-step research pipeline (generate queries, pick URLs, extract version)
  tools.py            Web tools: web_search (DDGS), web_fetch, web_fetch_batch (internal, not LLM-exposed)
  research.py         Orchestrates version research with iTunes fast path + LLM structured pipeline
  version_checker.py  Fast version checks: iTunes API, GitHub API
  system.py           macOS detection
  scanners/
    applications.py    Internal helpers: scan_applications, read_application, classify_source
  plugins/
    __init__.py        Re-exports ScannerPlugin as public API
    base.py            ScannerPlugin ABC with scan, scan_all, research, summarize interface
    registry.py        Plugin registry; discovers built-in + third-party plugins via entry points
    config.py          Plugin persistence: reads/writes ~/.config/checkupgrade/plugins.toml
    applications/      ApplicationsPlugin — scans /Applications and ~/Applications .app bundles
    homebrew/          HomebrewPlugin — brew outdated --json=v2, brew info --json=v2 --installed
    npm/               NpmPlugin — npm outdated -g --json, npm ls -g --depth=0 --json
```

## Plugin interface

```python
class ScannerPlugin(ABC):
    name: str
    enabled_by_default: bool = False
    display_color: str = "white"  # Rich color for result headers

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def scan(self, system) -> PluginScanResult: ...
    """Return items that need attention (outdated / to-research)."""

    def scan_all(self, system) -> PluginScanResult:
        """Return ALL installed items. Used when --all is passed. Default: =scan()."""
        return self.scan(system)

    def research(self, agent, item) -> UpdateCandidate | None:
        """Research latest version for a single item. Override to enable.
        Returns None if up-to-date or not possible. Default no-op."""

    @property
    def needs_research(self) -> bool:
        """True if subclass overrides research(). Auto-detected."""

    def summarize(self, agent, candidate) -> str | None:
        """Generate human-readable summary. Default: uses agent LLM."""
```

All plugins are registered via entry points in `pyproject.toml`:
```
applications = "checkupgrade.plugins.applications:ApplicationsPlugin"
homebrew = "checkupgrade.plugins.homebrew:HomebrewPlugin"
npm = "checkupgrade.plugins.npm:NpmPlugin"
```

## PluginScanResult

```python
@dataclass
class PluginScanResult:
    items: list[SoftwareItem]           # All discovered items
    candidates: list[UpdateCandidate]   # Already-confirmed updates
    skipped: list[str]                  # Skip reasons
```

## ScanResult

```python
@dataclass
class ScanResult:
    system: SystemProfile
    plugin_results: dict[str, PluginScanResult]  # plugin_name → result

    # Computed properties:
    all_candidates: list[UpdateCandidate]
    all_items: list[SoftwareItem]
    all_skipped: list[str]
```

## Concurrency model

Three layers of concurrency:

1. **Scan layer**: all enabled plugins run in parallel via a single `ThreadPoolExecutor`. Each plugin writes into its own `PluginScanResult` slot. Per-plugin progress tasks update independently.
2. **Research layer**: for plugins with `needs_research=True`, each unresearched item is processed concurrently (controlled by `-j`, default 10). Plugins without research skip this phase entirely.
3. **Summary layer**: AI summaries for all candidates across all plugins are generated concurrently.

## Research flow

Each non-App Store app goes through a structured 3-step pipeline:

1. **Generate queries**: LLM produces 2-3 search queries for the app. We execute all queries via `web_search` in parallel.
2. **Pick URLs**: LLM analyzes deduplicated search results and picks the top 3 most promising URLs.
3. **Extract version**: We fetch all 3 URLs via `web_fetch_batch`. LLM parses the content and returns version info.

App Store apps skip this entirely — they use the iTunes API directly (~1s).

Plugins that don't need research (Homebrew, npm) skip the LLM pipeline entirely — they know the latest version from their package manager.

## Data flow

**`advise` command**:
1. Select enabled plugins via `_select_plugins()` (respects `--apps-only`, `--plugins`)
2. Phase 1 — Scan: each plugin runs `scan()` (or `scan_all()` when `--all`) in parallel. One progress task per plugin.
3. Phase 2 — Research: for `needs_research` plugins only, research each item via `plugin.research(agent, item)` concurrently. Updates the same plugin progress task.
4. Phase 3 — Summaries: generate Chinese-language LLM summaries for all `all_candidates` in a single progress task.
5. Display with `_print_advise_result()` — when `--all`, shows up-to-date items grouped by plugin; without `--all`, only shows items with candidates.

## Key patterns

- **BYOK model**: LLM config merges env vars (`CHECKUPGRADE_LLM_*`) over file values. `require_raw_llm_config()` raises `ValueError` listing missing keys. API keys are never logged or printed in full.
- **Testing**: Uses `monkeypatch` (pytest fixture) for all external dependencies — subprocess, filesystem, env vars. No mock library.
- **Version comparison**: Uses `packaging.version.Version`; strips leading `v`/`V` before comparing.
- **Source classification**: Applications are classified as APP_STORE, LOCAL_BUILD, NETWORK_DOWNLOAD, APPLICATION, or UNKNOWN based on codesign authority, team ID, and quarantine xattr presence.
- **Structured LLM pipeline**: Agent does NOT use tool calling. Instead, 3 discrete LLM calls per app: generate queries, pick URLs, extract version. Each call returns JSON.
- **Logging**: `--verbose` sets INFO, `--debug` sets DEBUG. Logs go to stderr and `~/.local/state/checkupgrade/checkupgrade.log` by default. `--log-file` overrides path, `--no-log` disables file logging. Auto-truncates at 5MB.
- **Progress bar**: Each plugin gets its own `Progress` task row. Scanning fills the row with item/candidate counts. Research (if `needs_research`) updates the same row with progress. Summaries gets a dedicated row. For `show_all`, `scan_all()` is called instead of `scan()`.
- **Ignore list**: `~/.config/checkupgrade/ignore.txt` stores app IDs to skip during `advise`. Managed via `checkupgrade ignore add/remove/list`. Filtered after scan, before research.
- **Plugin discovery**: `registry.py` uses `importlib.metadata.entry_points(group="checkupgrade.plugins")` to discover all plugins at runtime. Built-in plugins (applications, homebrew, npm) are always present. Failed loads are logged, not fatal.
- **Plugin persistence**: `plugins/config.py` manages `~/.config/checkupgrade/plugins.toml`. Only explicitly-set plugins appear. `plugins enable/disable` persist state. `_select_plugins()` uses 3-tier precedence: CLI flags (`--apps-only`, `--plugins`) override persisted config, which overrides `enabled_by_default`.
