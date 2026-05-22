# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Task workflow

When the user signals a new implementation task (e.g. "新任务", "给你一个任务", "帮我实现", "加个功能"), follow these steps in order. For simple questions, bug reports, or quick checks, skip the workflow and respond directly.

1. **Enter plan mode** — do not write code before planning is approved.
2. **Research** — read CLAUDE.md and README.md, analyze recent git log for context.
3. **Impact analysis** — evaluate the task's impact on the full codebase.
4. **Write plan** — list detailed changes, files to touch, and implementation approach.
5. **Test coverage** — review existing tests and add new ones to cover all changed paths.
6. **Build binary** — run `uv run --extra build python scripts/build_binary.py` and verify with the built artifact.
7. **Update docs** — update CLAUDE.md and README.md to reflect the changes.
8. **Git commit** — Ask the user whether to commit. If yes, commit with Co-Authored-By using the model that performed the work (e.g. `DeepSeek-V4-Pro`, not a hardcoded Claude model name).

## Project overview

Frais is a macOS CLI that scans installed Applications, Homebrew packages, and npm global packages for available updates. It uses a curated set of 7 LLM providers (user-supplied key per provider) with a structured 3-step research pipeline for finding latest versions and generating update advice. Thinking-mode control is handled automatically per provider/model.

All scanning is plugin-based — the built-in `applications`, `homebrew`, and `npm` scanners are all `ScannerPlugin` implementations.

## Commands

```bash
# Development setup
uv sync --extra dev

# Run the CLI
uv run frais doctor
uv run frais advise
uv run frais advise --all
uv run frais advise --apps-only
uv run frais advise -j 5

# Run all tests
uv run pytest

# Run a single test file or test
uv run pytest tests/test_cli.py
uv run pytest tests/test_homebrew.py

# Build macOS binary (requires pyinstaller; --noupx for macOS compatibility)
uv run --extra build python scripts/build_binary.py
```

## Architecture

```
src/frais/
  __init__.py           # __version__ = "0.1.0"
  models.py             # Dataclasses: SystemProfile, SoftwareItem, UpdateCandidate,
                        #   PluginScanResult, ScanResult, ResearchResult, etc.
  providers.py          # Curated provider registry: 7 providers with models, URLs, thinking params
  config.py             # ProviderConfig: reads ~/.frais/config/config.toml, env var overrides
  llm.py                # LLMClient — chat, summarize_candidate, test_connection,
                        #   JSON helpers + LLMRequestError (generic LLM infrastructure)
  coordinator.py        # Orchestration: select_plugins, run_scan, run_summaries
                        #   Shared by advise, scan, summarize commands
  tools.py              # Web tools: web_search (DDGS), web_fetch, web_fetch_batch
  system.py             # macOS detection
  ignore.py             # Ignore list: load/save/add/remove (~/.frais/config/ignore.txt)
  cli.py                # Typer app: doctor, config, plugins, ignore
                        #   Action commands delegated to commands/ modules
  commands/
    __init__.py          # _split_plugins helper
    _scan_core.py        # run_scan_phase — shared Rich progress + cache logic
    advise.py            # advise command (scan + summaries + total time)
    scan.py              # scan command (agent-facing, --json output)
    summarize.py         # summarize <id> command (single-candidate summary)
    update.py            # update command (interactive confirmation → plugin.update)
  plugins/
    __init__.py          # Re-exports ScannerPlugin as public API
    base.py              # ScannerPlugin ABC: scan, scan_all, update, summarize
    _utils.py            # Shared helper: run_json() with env isolation for subprocess calls
    registry.py          # Plugin registry; discovers built-in + third-party plugins via entry points
    config.py            # Plugin persistence: reads/writes ~/.frais/config/plugins.toml
    applications/
      __init__.py        # ApplicationsPlugin + scan_applications, read_application, classify_source
      _store.py          # iTunes API (check_app_store_version, resolve_app_store_command)
      _research.py       # LLM 3-step pipeline (generate_search_queries, pick_urls,
                        #   extract_version) + version helpers + research_application_update
    homebrew/
      __init__.py        # HomebrewPlugin + brew info/uses helpers
    npm/
      __init__.py        # NpmPlugin
```

Design principle: all functionality is plugin-based. The CLI provides `plugins`, `config`, `ignore`, `doctor`. Agent-facing atomic commands: `scan` (structured output), `summarize <id>` (single summary), `update` (execute). `advise` is a convenience command = scan + summaries + display. Each plugin owns its entire scan pipeline internally — ApplicationsPlugin does discovery + LLM research in one call; Homebrew/npm do a single step. `applications/_store.py` and `applications/_research.py` are private to the applications plugin. `--plugins` respects persisted enable/disable state; disabled or unknown plugins show a warning.

## Plugin interface

```python
class ScannerPlugin(ABC):
    name: str
    enabled_by_default: bool = False
    display_color: str = "white"
    scan_steps: list[str] = []   # e.g. ["discovering apps", "researching"]

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def scan(self, system, on_progress=None, max_workers=10) -> PluginScanResult:
        """Discover items and determine which need updates.
        Plugins own their entire scan pipeline internally — ApplicationsPlugin
        does discovery + LLM research in one call; Homebrew/npm do a single step.
        on_progress(step_index, done, total) drives CLI progress bars."""

    def scan_all(self, system, on_progress=None, max_workers=10) -> PluginScanResult:
        """Return ALL installed items. Used when --all is passed."""
        return self.scan(system, on_progress=on_progress, max_workers=max_workers)

    def update(self, candidate) -> bool:
        """Execute the update. Default: subprocess.run(candidate.command).
        Override for plugin-specific behavior (e.g. App Store deep link)."""

    def summarize(self, llm, candidate) -> str | None:
        """Generate human-readable summary. Default: uses LLMClient.
        Called by CLI advise for each candidate. Override for custom summaries."""
```

All plugins are registered via entry points in `pyproject.toml`:
```
applications = "frais.plugins.applications:ApplicationsPlugin"
homebrew = "frais.plugins.homebrew:HomebrewPlugin"
npm = "frais.plugins.npm:NpmPlugin"
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

Two layers of concurrency:

1. **Scan layer**: `coordinator.run_scan()` — all plugins scan concurrently. Each plugin owns internal concurrency (ApplicationsPlugin uses `max_workers` for parallel LLM research; Homebrew/npm do a single subprocess call). Progress driven by `on_progress(step, done, total)` callback.
2. **Summary layer**: `coordinator.run_summaries()` — `plugin.summarize()` called concurrently for all candidates. Default delegates to `LLMClient.summarize_candidate()`.

## Progress bar

`_scan_core.run_scan_phase()` renders a Rich `Progress` bar. Each plugin gets one task row labeled with its `scan_steps`. The `on_progress` callback updates the task's description (step name) and completed/total. Per-task `TimeElapsedColumn` shows live elapsed time independently. After all scans, the total time (= max scan time + summarize time) is printed.

## Research flow (ApplicationsPlugin-private)

The LLM 3-step research pipeline lives in `plugins/applications/_research.py` — an internal implementation detail of `ApplicationsPlugin.scan()`, not a general capability.

Each non-App Store app goes through a structured 3-step pipeline:

1. **Generate queries**: LLM produces 2-3 search queries for the app. We execute all queries via `web_search` in parallel.
2. **Pick URLs**: LLM analyzes deduplicated search results and picks the top 3 most promising URLs.
3. **Extract version**: We fetch all 3 URLs via `web_fetch_batch`. LLM parses the content and returns version info.

App Store apps skip this entirely — they use the iTunes API directly (~1s).

Plugins that don't need research (Homebrew, npm) skip the LLM pipeline entirely — they know the latest version from their package manager.

## Data flow

**`advise` command**:
1. `coordinator.select_plugins()` (respects `--apps-only`, `--plugins`)
2. `_scan_core.run_scan_phase()` — concurrent scans with Rich progress. Each plugin owns its internal steps.
3. `coordinator.run_summaries()` — `plugin.summarize()` for each candidate, concurrently.
4. Display with `_print_advise_result()` — shows AI Analysis per candidate.

**`scan` command** (agent tool):
1. Same `_scan_core.run_scan_phase()` as advise step 2. `--json` skips progress bar.
2. Saves cache for `summarize`/`update` to consume.
3. Displays result (no summaries, no total time).

**`summarize <id>`** (agent tool):
1. Loads cached scan result, finds candidate by item_id.
2. Calls `plugin.summarize()`, writes `ai_summary` back to cache.
3. Prints result.

**`update [id]`**:
1. Loads cache, parses candidates, filters by optional id/name.
2. For each candidate: display info + AI Analysis → Proceed? → `plugin.update()`.

## Key patterns

- **Provider registry**: 7 curated LLM providers in `providers.py` as `Provider` dataclasses with `ModelInfo` lists and `thinking_param` definitions. `get_model_thinking_param()` returns the correct disable parameter only for models where `thinking_default=True`. Configuration stored as `[llm]` TOML with `provider`, `model`, `api_key`. `FRAIS_LLM_API_KEY` env var overrides the file-stored key; `OPENAI_API_KEY` serves as fallback for the openai provider. API keys are never logged or printed in full.
- **Testing**: Uses `monkeypatch` (pytest fixture) for all external dependencies — subprocess, filesystem, env vars. No mock library.
- **Version comparison**: Uses `packaging.version.Version`; strips leading `v`/`V` before comparing.
- **Source classification**: Applications are classified as APP_STORE, LOCAL_BUILD, NETWORK_DOWNLOAD, APPLICATION, or UNKNOWN based on codesign authority, team ID, and quarantine xattr presence.
- **Structured LLM pipeline**: Uses 3 discrete LLM calls per app (not tool-calling / agentic). Each call returns structured JSON. This is intentional — earlier attempts with LLM tool-calling produced unreliable results.
- **Logging**: `--verbose` sets INFO, `--debug` sets DEBUG. Logs go to stderr and `~/.frais/log/frais.log` by default. `--log-file` overrides path, `--no-log` disables file logging. Auto-truncates at 5MB.
- **Progress bar**: Each plugin gets its own `Progress` task row. Scanning fills the row with item/candidate counts. Research (if `needs_research`) updates the same row with progress. Summaries gets a dedicated row. For `show_all`, `scan_all()` is called instead of `scan()`.
- **Ignore list**: `~/.frais/config/ignore.txt` stores app IDs to skip during `advise`. Auto-created on first access via `init_ignored()`. Managed via `frais ignore add/remove/list`. Filtered after scan, before research.
- **Plugin discovery**: `registry.py` uses `importlib.metadata.entry_points(group="frais.plugins")` to discover all plugins at runtime. Built-in plugins (applications, homebrew, npm) are always present. Failed loads are logged, not fatal.
- **Plugin persistence**: `plugins/config.py` manages `~/.frais/config/plugins.toml`. First run auto-creates the file with all discovered plugins set to their defaults. `plugins enable/disable` persist state. `_select_plugins()` uses 3-tier precedence: CLI flags (`--apps-only`, `--plugins`) override persisted config, which overrides `enabled_by_default`.
- **Ctrl+C handling**: `advise` registers a SIGINT handler before entering the Progress/ThreadPoolExecutor block. The handler uses `os.write(1, b"\033[?25h\n")` to directly write the cursor-show ANSI escape to the stdout fd — bypassing Rich's internal segment buffer, which can swallow escapes when a nested `with self.console:` context is held (e.g. by Progress's auto-refresh thread). Then `os._exit(130)`. Original handler is restored via `try/finally`. Signal handler (not KeyboardInterrupt) is needed because ThreadPoolExecutor.__exit__ blocks on worker threads. The handler must only call async-signal-safe functions (`os.write`, `os._exit`) — no logging, no Rich API calls, no string formatting.
- **Subprocess env isolation**: `run_json()` in `plugins/_utils.py` and `_brew_uses()` in `plugins/homebrew.py` clear `DYLD_LIBRARY_PATH` from the subprocess environment to prevent PyInstaller-bundled dylibs from interfering with system commands.
