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
  llm.py                # LLMClient — structured 3-step research calls (generate queries, pick URLs,
                        #   extract version) + JSON helpers + LLMRequestError
  tools.py              # Web tools: web_search (DDGS), web_fetch, web_fetch_batch
  summarize.py          # Batch LLM summary generation (generate_summaries)
  system.py             # macOS detection
  ignore.py             # Ignore list: load/save/add/remove (~/.frais/config/ignore.txt)
  cli.py                # Typer app: doctor, advise, update, config, plugins, ignore
                        #   CLI is a pure dispatcher — all business logic lives in plugins
  plugins/
    __init__.py          # Re-exports ScannerPlugin as public API
    base.py              # ScannerPlugin ABC: scan, scan_all, research, update, summarize
    _utils.py            # Shared helper: run_json() with env isolation for subprocess calls
    registry.py          # Plugin registry; discovers built-in + third-party plugins via entry points
    config.py            # Plugin persistence: reads/writes ~/.frais/config/plugins.toml
    applications/
      __init__.py        # ApplicationsPlugin + scan_applications, read_application, classify_source
      _store.py          # iTunes API (check_app_store_version, resolve_app_store_command)
      _research.py       # LLM 3-step pipeline + version helpers (_is_newer, _normalize, etc.)
    homebrew/
      __init__.py        # HomebrewPlugin + brew info/uses helpers
    npm/
      __init__.py        # NpmPlugin
```

Design principle: all functionality is plugin-based. The CLI only provides `plugins`, `config`, `ignore`, and `doctor` commands. The `advise` command is a pure dispatcher that delegates everything (scan, research, update) to plugins via the `ScannerPlugin` ABC. Each plugin lives in its own subdirectory under `plugins/`. `applications/_store.py` and `applications/_research.py` are private to the applications plugin — the iTunes fast path and LLM research pipeline are internal implementation details of `ApplicationsPlugin`, not general capabilities.

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

    def research(self, llm, item) -> UpdateCandidate | None:
        """Research latest version for a single item. Override to enable.
        Returns None if up-to-date or not possible. Default no-op."""

    @property
    def needs_research(self) -> bool:
        """True if subclass overrides research(). Auto-detected."""

    def update(self, candidate) -> bool:
        """Execute the update. Default: subprocess.run(candidate.command).
        Override for plugin-specific behavior (e.g. App Store deep link)."""

    @property
    def needs_update(self) -> bool:
        """True if subclass overrides update(). Auto-detected."""

    def summarize(self, llm, candidate) -> str | None:
        """Generate human-readable summary. Default: uses LLMClient."""
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

Three layers of concurrency:

1. **Scan layer**: all enabled plugins run in parallel via a `ThreadPoolExecutor`. Each plugin writes into its own `PluginScanResult` slot.
2. **Research layer**: research tasks are submitted as soon as each plugin's scan completes. Research completions are interleaved with pending scan completions via `wait(FIRST_COMPLETED)`, so progress updates immediately rather than waiting for all scans to finish. Concurrency controlled by `-j` (default 10).
3. **Summary layer**: AI summaries for all candidates across all plugins are generated concurrently.

## Research flow (ApplicationsPlugin-private)

The LLM 3-step research pipeline lives in `plugins/applications/_research.py` — it is an internal implementation detail of `ApplicationsPlugin`, not a general capability.

Each non-App Store app goes through a structured 3-step pipeline:

1. **Generate queries**: LLM produces 2-3 search queries for the app. We execute all queries via `web_search` in parallel.
2. **Pick URLs**: LLM analyzes deduplicated search results and picks the top 3 most promising URLs.
3. **Extract version**: We fetch all 3 URLs via `web_fetch_batch`. LLM parses the content and returns version info.

App Store apps skip this entirely — they use the iTunes API directly (~1s).

Plugins that don't need research (Homebrew, npm) skip the LLM pipeline entirely — they know the latest version from their package manager.

## Data flow

**`advise` command**:
1. Select enabled plugins via `_select_plugins()` (respects `--apps-only`, `--plugins`)
2. Scan + Research interleaved: all plugin scans submitted to a scan pool. As each scan completes, research tasks are submitted to a research pool and their futures tracked. A single `while pending:` loop with `wait(FIRST_COMPLETED)` handles both scan and research completions, so progress bars update immediately — no waiting for slow scans (e.g. homebrew) to finish before showing fast scan (applications) research progress.
3. Summaries: generate Chinese-language LLM summaries for all `all_candidates` in a single progress task.
4. Display with `_print_advise_result()` — when `--all`, shows up-to-date items grouped by plugin; without `--all`, only shows items with candidates.

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
