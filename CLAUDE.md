# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 首要开发规范

**所有代码必须满足 `python_engineering_spec_strict.md` 的要求。** 该规范是本项目的第一优先级约束，任何代码变更前必须确认符合规范。关键红线：

- 超长函数 / 超长类 —— 禁止
- 无类型代码 —— 禁止
- 裸 except / 吞异常 —— 禁止
- print 调试 —— 禁止
- 硬编码 —— 禁止
- 全局状态污染 —— 禁止
- 无测试提交 —— 禁止
- import * / 动态 monkey patch —— 禁止

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

Frais is a macOS CLI that scans installed Applications, Homebrew packages, and npm global packages for available updates. It uses the DeepSeek LLM API (user-supplied key) with a structured 3-step research pipeline for finding latest versions and generating update advice. Extended thinking is enabled automatically when the selected model supports it, with per-provider parameter injection handled by protocol-specific Client subclasses.

All scanning is plugin-based — the built-in `applications`, `homebrew`, and `npm` scanners are all `ScannerPlugin` implementations.

Frais is **not an AI agent**. It is a deterministic command-line tool: each command does one
thing and exits. The `--json` output provides structured data that external tools can consume —
build a GUI, feed results to scripts, or integrate into larger workflows. Frais itself has no
multi-step reasoning, no tool-calling loop, and no conversational state. Wrapping it in a GUI
or a script is straightforward; turning it into a native MCP Server or autonomous agent
requires a significant architectural rewrite (the plugin model is "plugin owns the full
pipeline", which is incompatible with agent-style step-by-step orchestration).

## Commands

```bash
# Development setup
uv sync --extra dev

# Run the CLI
uv run frais doctor
uv run frais advise
uv run frais advise --all
uv run frais advise -j 5

# Run all tests
uv run pytest

# Run a single test file or test
uv run pytest tests/test_cli.py
uv run pytest tests/test_homebrew.py

# Build macOS binary (onedir mode for fast startup, requires pyinstaller)
uv run --extra build python scripts/build_binary.py

# Test the built binary
dist/frais/frais doctor
dist/frais/frais plugins list

# Distribute: zip the frais/ directory + frais.sh, user runs:
bash frais.sh doctor    # first run installs to ~/.frais/bin/, subsequent runs are instant
```

## Architecture

```
src/frais/
  __init__.py           # __version__ = "0.1.0"
  models.py             # Dataclasses: SystemProfile, SoftwareItem, UpdateCandidate,
                        #   PluginScanResult, ScanResult, ResearchResult, etc.
  providers.py          # Provider/ModelInfo dataclasses; DeepSeek provider definition
  store/                # Persistent storage layer
    config_store.py      #   ProviderConfig + config.toml CRUD, env var overrides
    plugin_store.py      #   Plugin state: reads/writes plugins.toml
    ignore_store.py      #   Ignore list: ignore.txt CRUD
    scan_cache.py        #   Atomic last_advice.json cache writes
  llm/                  # LLM client layer (multi-protocol, per-provider)
    __init__.py          #   _CLIENT_MAP registry + get_client() factory
    _base.py             #   LLMClient ABC + LLMRequestError
    _openai_compatible.py  # OpenAICompatibleClient base (Bearer auth, /v1/chat/completions)
    _deepseek.py         #   DeepSeekOpenAIClient + DeepSeekAnthropicClient (stub)
    _anthropic.py        #   AnthropicClient stub (reserved for future)
  coordinator.py        # Orchestration: select_plugins, run_scan, run_summaries
                        #   Shared by advise, scan, summarize commands
  web_tools.py          # Web tools: web_search (DDGS), web_fetch, web_fetch_batch
  system.py             # macOS detection
  paths.py              # Shared runtime paths for logs and scan cache
  logging_config.py     # Logging setup and file truncation
  ignore_filter.py      # Applies ignore.txt to ScanResult
  cli.py                # Typer app assembly and command registration only
  commands/
    __init__.py          # _split_plugins helper
    doctor.py            # doctor command
    _output.py           # print_json_success() + exit_with_error() — shared JSON/CLI output helpers
    _scan_core.py        # run_scan_phase — shared scan/progress orchestration
    _signal.py           # install_interrupt_handler() — shared SIGINT handler for advise/scan
    advise.py            # advise command (scan + summaries, helpers <50 lines each)
    config.py            # config commands: manage (interactive), show, path, test
    ignore.py            # ignore commands: list, add, remove
    plugins.py           # plugins commands: list, enable, disable
    scan.py              # scan command (agent-facing, --json output)
    summarize.py         # summarize <id> command (single-candidate summary)
    update.py            # update command (helpers: load, parse, filter, execute loop)
  ui/
    __init__.py
    scan_progress.py     # Rich progress bar rendering extracted from _scan_core.py
  plugins/
    __init__.py          # Re-exports ScannerPlugin as public API
    base.py              # ScannerPlugin ABC: scan, scan_all, update, summarize
    subprocess_json.py   # Shared helper: run_json() with env isolation for subprocess calls
    registry.py          # Plugin registry; discovers built-in + third-party plugins via entry points
    applications/
      __init__.py        # Re-exports: ApplicationsPlugin, scan_applications, classify_source
      plugin.py          # ApplicationsPlugin class
      discovery.py       # scan_applications, read_application
      source_classifier.py # classify_source, _path_id, _signing_summary, _quarantine_summary
      app_store.py       # iTunes API (check_app_store_version, resolve_app_store_command)
      research/          # LLM 3-step pipeline (split from monolithic _research.py)
        __init__.py       #   Re-exports all symbols
        pipeline.py       #   research_application_update, _llm_structured_research,
                         #     generate_search_queries, pick_urls, extract_version
        prompts.py        #   _SEARCH_QUERIES_PROMPT, _PICK_URLS_PROMPT, _EXTRACT_VERSION_PROMPT
        json_parser.py    #   _extract_json, _parse_json_list, _parse_json_object, _ensure_list
        candidate_factory.py # _make_candidate
        version_compare.py   # _is_newer, _normalize, _digits_only
    homebrew/
      __init__.py        # Re-exports: HomebrewPlugin
      plugin.py          # HomebrewPlugin + _brew_info, _brew_uses, _first, etc.
    npm/
      __init__.py        # Re-exports: NpmPlugin
      plugin.py          # NpmPlugin + _make_candidate
```

Design principle: all functionality is plugin-based. The CLI provides `plugins`, `config`, `ignore`, `doctor`. Commands with `--json` output (`scan`, `summarize`) are designed for consumption by external LLM agents. `update` is interactive. `advise` is a convenience command = scan + summaries + display. Each plugin owns its entire scan pipeline internally — ApplicationsPlugin does discovery + LLM research in one call; Homebrew/npm do a single step. `applications/app_store.py` and `applications/research/` are private to the applications plugin. `--plugins` respects persisted enable/disable state; disabled or unknown plugins show a warning.

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
applications = "frais.plugins.applications.plugin:ApplicationsPlugin"
homebrew = "frais.plugins.homebrew.plugin:HomebrewPlugin"
npm = "frais.plugins.npm.plugin:NpmPlugin"
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

    # Computed property:
    all_candidates: list[UpdateCandidate]
```

## Concurrency model

Two layers of concurrency:

1. **Scan layer**: `coordinator.run_scan()` — all plugins scan concurrently. Each plugin owns internal concurrency (ApplicationsPlugin uses `max_workers` for parallel LLM research; Homebrew/npm do a single subprocess call). Progress driven by `on_progress(step, done, total)` callback.
2. **Summary layer**: `coordinator.run_summaries()` — `plugin.summarize()` called concurrently for all candidates. Default delegates to `commands/summarize.summarize_candidate()`.

## Progress bar

`_scan_core.run_scan_phase()` delegates Rich rendering to `ui/scan_progress.py`. Each plugin gets one task row labeled with its `scan_steps`. The `on_progress` callback updates the task's description (step name) and completed/total. Per-task `TimeElapsedColumn` shows live elapsed time independently. After all scans, the total time (= max scan time + summarize time) is printed.

## Research flow (ApplicationsPlugin-private)

The LLM 3-step research pipeline lives in `plugins/applications/research/` — an internal implementation detail of `ApplicationsPlugin.scan()`, not a general capability. The module is split by responsibility: `pipeline.py` (orchestration), `prompts.py` (constants), `json_parser.py` (LLM output parsing), `candidate_factory.py` (UpdateCandidate construction), `version_compare.py` (normalization and comparison).

Each non-App Store app goes through a structured 3-step pipeline:

1. **Generate queries**: LLM produces 2-3 search queries for the app. We execute all queries via `web_search` in parallel.
2. **Pick URLs**: LLM analyzes deduplicated search results and picks the top 3 most promising URLs.
3. **Extract version**: We fetch all 3 URLs via `web_fetch_batch`. LLM parses the content and returns version info.

App Store apps skip this entirely — they use the iTunes API directly (~1s).

Plugins that don't need research (Homebrew, npm) skip the LLM pipeline entirely — they know the latest version from their package manager.

## Data flow

**`advise` command**:
1. `coordinator.select_plugins()` (respects `--plugins`, persisted enable/disable state)
2. `_scan_core.run_scan_phase()` — concurrent scans with Rich progress. Each plugin owns its internal steps.
3. `coordinator.run_summaries()` — `plugin.summarize()` for each candidate, concurrently.
4. Display with `_print_advise_result()` — shows AI Analysis per candidate.

**`scan` command** (`--json` output for external LLM consumption):
1. Same `_scan_core.run_scan_phase()` as advise step 2. `--json` skips progress bar.
2. Saves cache for `summarize`/`update` to consume.
3. Displays result (no summaries, no total time).

**`summarize <id>`** (`--json` output for external LLM consumption):
1. Loads cached scan result, finds candidate by item_id.
2. Calls `plugin.summarize()`, writes `ai_summary` back to cache.
3. Prints result.

**`update [id]`**:
1. Loads cache, parses candidates, filters by optional id/name.
2. For each candidate: display info + AI Analysis → Proceed? → `plugin.update()`.

## JSON output formats

All commands that support `--json` follow a unified **LLM Agent Contract**: the JSON output is designed so an external LLM can consume it deterministically — parse it, branch on structured fields, and produce consistent repeatable responses. Without `--json`, commands emit Rich-formatted text only.

### Universal envelope

```json
// Success — ok is always true, always the first key:
{"ok": true, ...command-specific fields}

// Error — ok is always false, error then reason then hint then context fields:
{"ok": false, "error": "<what happened>", "reason": "<stable enum>", "hint": "<what to do next>", ...context}
```

**Invariants** (guaranteed across all commands, all versions):

1. `ok` is always the first key and always a boolean.
2. On error, `error` is always the second key (human-readable), `reason` is always the third (stable machine enum), `hint` is always the fourth (actionable next step).
3. Additional context keys (`item_id`, `plugin_name`, `requested`) carry structured data for LLM branching — they appear on error responses where relevant.
4. Exit code `0` = success. Exit code `1` = general error. Exit code `2` = config/parameter error.
5. `null` always means "not yet computed" — never "I forgot to include this."
6. Empty list `[]` means "checked and found nothing" — never "I didn't check."
7. **IDs round-trip**: an `id` from `scan --json` is a valid argument to `summarize <id>` and `update <id>`. A plugin `name` from `plugins list --json` is a valid argument to `plugins enable/disable <name>`. An `app_id` from `ignore list --json` is a valid argument to `ignore add/remove <app_id>`.
8. Enum values (SourceKind, risk_level, impact_level, reason, action) are lowercased stable strings — the full set is documented below.

### Error reasons (stable enum)

Every error response includes a `reason` field the LLM can branch on:

| `reason` | Meaning | Commands that return it |
|----------|---------|------------------------|
| `config_missing` | No LLM provider configured | advise, summarize, config test |
| `connection_error` | LLM connection failed | config test |
| `no_plugins_matched` | All requested plugins unavailable or disabled | scan, advise |
| `unknown_plugin` | Plugin name not in registry | plugins enable, plugins disable |
| `plugin_not_found` | Plugin from cache no longer installed | summarize |
| `no_cache` | No scan cache file exists | summarize |
| `cache_read_error` | Cache file exists but is corrupt | summarize |
| `candidate_not_found` | ID not in cached scan results | summarize |

### Shared helpers (`commands/_output.py`)

- `print_json_success(**kwargs)` — prints `{"ok": true, ...}` to stdout via Rich `print_json`. The `ok` key is reserved; callers cannot override it.
- `exit_with_error(message, json_mode, exit_code=1, reason="", hint="", **extra)` — in JSON mode prints `{"ok": false, "error": message, "reason": reason, "hint": hint, ...extra}` to stdout then `raise typer.Exit(code)`. In CLI mode prints red error text (+ dim hint) to stderr then exits.

### doctor --json

```json
{
  "ok": true,
  "system": {
    "os_name": "macOS",           // OS display name
    "os_version": "26.5",         // OS version string
    "arch": "arm64",              // CPU architecture (arm64 / x86_64)
    "applications_paths": ["/Applications", "~/Applications"]
  },
  "plugins": {
    "<name>": {
      "available": "yes|no",      // Whether the underlying tool is installed
      "default": "enabled|disabled"  // Plugin's enabled_by_default value
    }
  },
  "llm": null | {
    "configured": true|false,     // Whether config is ready to use
    "provider": "deepseek",       // Provider id string
    "model": "deepseek-v4-flash", // Model id string
    "key_suffix": "***abcd"       // Last 4 chars of API key, masked
  }
}
```

### plugins list --json

```json
{
  "ok": true,
  "plugins": [
    {
      "name": "applications",     // Plugin name (entry point name)
      "available": "yes|no",      // is_available() result
      "default": "enabled|disabled",  // enabled_by_default value
      "effective": "enabled|disabled" // Actual state after persisted overrides
    }
  ]
}
```

### plugins enable/disable --json

```json
// Success:
{"ok": true, "plugin": "homebrew", "action": "enabled|disabled"}

// Error (unknown plugin):
{"ok": false, "error": "Unknown plugin: <name>"}
```

### ignore list --json

```json
{
  "ok": true,
  "ignored": ["com.example.app", ...],  // Sorted list of ignored bundle IDs
  "count": 2                            // Number of ignored apps
}
```

### ignore add/remove --json

```json
// add:
{"ok": true, "app_id": "com.example.app", "action": "added|already_ignored"}

// remove:
{"ok": true, "app_id": "com.example.app", "action": "removed|not_in_list"}
```

### config show --json

```json
// Not configured:
{"ok": true, "configured": false}

// Configured:
{
  "ok": true,
  "configured": true,
  "provider": "deepseek",        // Provider id
  "model": "deepseek-v4-flash",  // Model id
  "key_suffix": "***abcd",       // Masked key suffix (null if no key set)
  "key_source": "env:FRAIS_LLM_API_KEY|env:OPENAI_API_KEY|config",  // Where the key came from
}
```

### config test --json

```json
// Success:
{
  "ok": true,
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "url": "https://api.deepseek.com",
  "response": "LLM response text"
}

// Error:
{"ok": false, "error": "...", "reason": "config_missing|connection_error", "hint": "..."}
```

### config path --json

```json
{"ok": true, "path": "/Users/hpy/.frais/config/config.toml"}
```

`config manage` is interactive only — ``--json`` is not supported. See `frais config manage --help`.

### scan --json / advise --json

Both commands output a serialized `ScanResult` wrapped in the success envelope:

```json
{
  "ok": true,
  "system": {
    "os_name": "macOS",
    "os_version": "26.5",
    "arch": "arm64",
    "applications_paths": ["/Applications", "~/Applications"]
  },
  "plugin_results": {
    "<plugin_name>": {
      "items": [
        {
          "id": "com.google.Chrome",     // Unique identifier (bundle ID, brew:name, npm:name)
          "name": "Google Chrome",       // Display name
          "kind": "application",         // App kind (application, formula, cask, npm package, etc.)
          "source": "network download",  // SourceKind enum value — how it was installed
          "current_version": "131.0.6778.265",
          "path": "/Applications/Google Chrome.app",
          "metadata": {}                 // Plugin-specific extra data (e.g. bundle_identifier)
        }
      ],
      "candidates": [
        {
          "item": { ... },               // SoftwareItem (same structure as above)
          "latest_version": "132.0.6834.210",
          "release_notes": null,
          "dependency_impact": {
            "used_by": [],               // Reverse deps (brew uses, npm dependents)
            "depends_on": [],            // Forward deps
            "impact_level": "unknown"    // unknown | low | medium | high
          },
          "risk_level": "low",           // low | medium | high | unknown
          "ai_summary": "## What's New\n...",  // LLM-generated Markdown summary
          "recommended_action": "Update",      // Update | No action | Manual | etc.
          "can_auto_update": true,       // Whether plugin.update() can execute directly
          "command": ["brew", "upgrade", "google-chrome"],  // Shell command for auto_update
          "evidence": ["https://..."]    // URLs that sourced the version info
        }
      ],
      "skipped": ["reason string"]       // Items/errors that were skipped
    }
  }
}
```

**Key field notes for agent consumption:**
- `item.id`: globally unique; prefix indicates source (`brew:`, `npm:`, or bare bundle ID)
- `item.source`: one of `SourceKind` enum — `application`, `local build`, `network download`, `app store`, `brew`, `brew cask`, `npm`, `unknown`
- `candidate.can_auto_update`: when `true`, the `command` list is safe to execute
- `candidate.recommended_action`: human-readable guidance; `"No action"` means up-to-date
- `candidate.evidence`: URLs that were fetched to determine the latest version
- `candidate.ai_summary`: may be `null` if summaries haven't been run yet (scan without advise)

### summarize --json <id>

```json
// Success:
{"ok": true, "item_id": "com.google.Chrome", "ai_summary": "## What's New\n..."}

// Error:
{"ok": false, "error": "No scan cache found. Run `frais advise` or `frais scan` first."}
{"ok": false, "error": "No candidate found for: <id>"}
```

### Error format (all commands)

```json
{
  "ok": false,
  "error": "<human-readable what happened>",
  "reason": "<stable machine enum — see table above>",
  "hint": "<actionable next step for the LLM to follow or tell the user>",
  ...context fields (item_id, plugin_name, requested — vary by reason)
}
```

Error exit codes: `1` for general errors, `2` for config/parameter errors (matches `typer.BadParameter` convention).

The LLM should branch on `reason` (stable enum), not on `error` (natural language). The `hint` field tells the LLM what command to run next or what to tell the user.

### Command contract summary

Each `--json` command is a deterministic function: same state → same output. An LLM can reason about inputs and outputs from this table:

| Command | Precondition | Key success fields | Error reasons | Next command |
|---------|-------------|-------------------|---------------|--------------|
| `doctor --json` | none | `system`, `plugins.<name>.available`, `llm.configured` | (none — always succeeds) | `config manage` if `!llm.configured` |
| `config show --json` | none | `configured`, `provider`, `key_source` | (none) | `config test` to verify |
| `config test --json` | config exists | `provider`, `model`, `url`, `response` | `config_missing`, `connection_error` | `scan` or `advise` |
| `config path --json` | none | `path` | (none) | — (informational) |
| `plugins list --json` | none | `plugins[].name`, `.available`, `.effective` | (none) | `plugins enable/disable <name>` |
| `plugins enable/disable --json <name>` | plugin exists | `plugin`, `action` | `unknown_plugin` | `plugins list` to verify |
| `ignore list --json` | none | `ignored[]`, `count` | (none) | `ignore add/remove <id>` |
| `ignore add/remove --json <id>` | none | `app_id`, `action` | (none) | `ignore list` to verify |
| `scan --json` | LLM optional | `plugin_results.<plugin>.items[]`, `.candidates[]` | `no_plugins_matched` | `summarize <id>` or `update <id>` |
| `advise --json` | LLM configured | same as `scan` + `ai_summary` populated | `config_missing`, `no_plugins_matched` | `update <id>` |
| `summarize --json <id>` | cache exists | `item_id`, `ai_summary` | `no_cache`, `cache_read_error`, `candidate_not_found`, `plugin_not_found`, `config_missing` | `update <id>` |

### LLM agent workflow

An LLM agent consuming frais JSON output should follow this decision tree:

```
1. doctor --json
   ├─ llm.configured == false → tell user "Run frais config manage"
   ├─ any plugin.available == "no" → warn user, proceed with available
   └─ ok → continue

2. scan --json  (use advise --json if AI summaries wanted immediately)
   ├─ reason == "no_plugins_matched" → tell user "No plugins available"
   └─ ok → for each candidate: check latest_version vs current_version

3. For each candidate where ai_summary is null and user wants details:
   summarize --json <candidate.item.id>
   ├─ reason == "no_cache" → tell user "Run frais scan --json first"
   ├─ reason == "candidate_not_found" → check the id, suggest scan
   └─ ok → display ai_summary to user

4. update <candidate.item.id> — interactive, LLM cannot automate.
   Present the command to the user and explain the risk_level.
```

### Recommended agent system prompt

To use frais as a tool in any LLM agent, include this in the agent's system prompt:

```
You have access to the `frais` CLI for checking macOS software updates.
All read commands accept `--json` and return a uniform JSON envelope.

Envelope:
  Success: {"ok": true, ...fields}
  Error:   {"ok": false, "error": "...", "reason": "<enum>", "hint": "...", ...context}

Rules for consuming frais output:
1. Branch on `ok` first — true = success path, false = error path.
2. On error, branch on `reason` (stable enum values, not natural language):
   - config_missing → tell user to run `frais config manage`
   - connection_error → suggest checking API key and network
   - no_cache → tell user to run `frais scan --json` first
   - candidate_not_found → suggest running `frais scan --json` to refresh
   - unknown_plugin → tell user to run `frais plugins list --json`
   - plugin_not_found → the plugin was removed from the system
   - no_plugins_matched → tell user no requested plugins are available
   - cache_read_error → suggest deleting ~/.frais/log/last_advice.json and rescanning
3. Follow the `hint` field — it tells you the next action.
4. IDs round-trip: an id from scan is the exact argument for summarize and update.
5. `null` = not yet computed. `[]` = checked, none found.
6. `can_auto_update: true` means the `command` list is safe to execute.
7. `recommended_action: "No action"` means the item is already up to date.

Workflow:
   doctor --json → scan --json → summarize --json <id> → present to user
   `update` is interactive — tell the user to run it, do not automate.
```

## Key patterns

- **Provider registry**: Providers defined in `providers.py` as `Provider` dataclasses with `ModelInfo` entries (`supports_thinking` flag). No provider-specific logic in the data layer. Configuration stored as `[llm]` TOML with `provider`, `model`, `api_key`. `FRAIS_LLM_API_KEY` env var overrides the file-stored key. API keys are never logged or printed in full.
- **LLM client layer**: `llm/` package — protocol-agnostic ABC (`LLMClient`) with `OpenAICompatibleClient` as the base implementation and `DeepSeekOpenAIClient` for DeepSeek-specific thinking injection. Factory `get_client(config, protocol)` selects by `(provider_id, protocol)` from `_CLIENT_MAP`. Each provider subclass overrides `_apply_thinking()` to inject its own thinking control parameters via `extra_body`. `summarize_candidate()` is a standalone function in `commands/summarize.py`, not a Client method.
- **JSON/CLI output**: `commands/_output.py` provides `print_json_success(**kwargs)` and `exit_with_error(message, json_mode, exit_code=1)`. Every command uses these two helpers — errors are a single function call with no branching in the command body; success output is one `if json_output:` / `else:` at the end. The `ok` key in `print_json_success` is reserved (caller-provided `ok` is discarded). `exit_with_error` uses Rich stderr Console for CLI mode to match `click.ClickException` behavior.
- **Testing**: Uses `monkeypatch` (pytest fixture) for all external dependencies — subprocess, filesystem, env vars. No mock library.
- **Version comparison**: Uses `packaging.version.Version`; strips leading `v`/`V` before comparing.
- **Source classification**: Applications are classified as APP_STORE, LOCAL_BUILD, NETWORK_DOWNLOAD, APPLICATION, or UNKNOWN based on codesign authority, team ID, and quarantine xattr presence.
- **Structured LLM pipeline**: Uses 3 discrete LLM calls per app (not tool-calling / agentic). Each call returns structured JSON. This is intentional — earlier attempts with LLM tool-calling produced unreliable results.
- **Logging**: `--verbose` sets INFO, `--debug` sets DEBUG. Logs go to stderr and `~/.frais/log/frais.log` by default. `--log-file` overrides path, `--no-log` disables file logging. Auto-truncates at 5MB.
- **Progress bar**: `_scan_core.run_scan_phase()` renders a Rich `Progress` bar with one task row per plugin. Each row shows the plugin's current `scan_steps` label with live `TimeElapsedColumn`. Progress is driven by `on_progress(step, done, total)`. After scans, a dedicated task row shows Summaries progress. Total time = max(scan times) + summarize time.
- **Ignore list**: `~/.frais/config/ignore.txt` stores app IDs to skip during `advise`. Auto-created on first access via `init_ignored()`. Managed via `frais ignore add/remove/list`. Filtered after scan, before research.
- **Plugin discovery**: `registry.py` uses `importlib.metadata.entry_points(group="frais.plugins")` to discover all plugins at runtime. Built-in plugins (applications, homebrew, npm) are always present. Failed loads are logged, not fatal.
- **Lazy imports**: The applications plugin defers heavy imports (`scan_applications`, `research_application_update`) into its `scan()` method body. This prevents `all_plugins()` — called by lightweight commands like `plugins list` and `doctor` — from pulling in the LLM client, DDGS, and lxml import chain.
- **Plugin persistence**: `store/plugin_store.py` manages `~/.frais/config/plugins.toml`. First run auto-creates the file with all discovered plugins set to their defaults. `plugins enable/disable` persist state. `select_plugins()` precedence: `--plugins` (explicit) overrides persisted config; default path uses `enabled_by_default` when not persisted.
- **Ctrl+C handling**: `advise` and `scan` use `commands/_signal.install_interrupt_handler()` — a shared SIGINT handler. It uses `os.write(1, b"\033[?25h\n")` (wrapped in `try/except OSError`) to directly write the cursor-show ANSI escape to the stdout fd — bypassing Rich's internal segment buffer, which can swallow escapes when a nested `with self.console:` context is held (e.g. by Progress's auto-refresh thread). Then `os._exit(130)`. Original handler is restored via `try/finally`. Signal handler (not KeyboardInterrupt) is needed because ThreadPoolExecutor.__exit__ blocks on worker threads. The handler must only call async-signal-safe functions (`os.write`, `os._exit`) — no logging, no Rich API calls, no string formatting.
- **Atomic writes**: Config and state files (`config.toml`, `ignore.txt`, `plugins.toml`, `last_advice.json`) are written to a `.tmp` sibling then atomically renamed via `Path.replace()` to prevent truncated/corrupt reads on concurrent access or crash.
- **Subprocess env isolation**: All subprocess calls (`run_json()` in `plugins/subprocess_json.py`, `_brew_uses()` in `plugins/homebrew/plugin.py`, `_signing_summary()` and `_quarantine_summary()` in `plugins/applications/source_classifier.py`) clear `DYLD_LIBRARY_PATH` from the subprocess environment to prevent PyInstaller-bundled dylibs from interfering with system commands.
