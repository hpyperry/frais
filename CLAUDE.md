# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 首要开发规范

**所有代码必须保持高标准**。关键红线：

- 超长函数（>100行）/ 超长结构体 —— 拆分为更小的单元
- `unwrap()` / `expect()` 在非测试代码中 —— 使用 `Result` 或适当的错误处理
- 裸 `panic!` —— 使用 `log::error!` + 优雅降级
- 硬编码 —— 提取为常量或配置
- 全局可变状态 —— 禁止
- 无测试提交 —— 禁止
- `unsafe` 代码 —— 除非有充分理由且注释说明，否则禁止

## Task workflow

When the user signals a new implementation task, follow these steps in order. For simple questions, bug reports, or quick checks, skip the workflow and respond directly.

1. **Enter plan mode** — do not write code before planning is approved.
2. **Research** — read CLAUDE.md and README.md, analyze recent git log for context.
3. **Impact analysis** — evaluate the task's impact on the full codebase.
4. **Write plan** — list detailed changes, files to touch, and implementation approach.
5. **Test coverage** — review existing tests and add new ones to cover all changed paths.
6. **Build binary** — run `cargo build --release` and verify with the built artifact.
7. **Update docs** — update CLAUDE.md and README.md to reflect the changes.
8. **Git commit** — Ask the user whether to commit. If yes, commit with Co-Authored-By using the model that performed the work.

## Project overview

Frais is a macOS CLI that scans installed Applications, Homebrew packages, and npm global packages for available updates. It uses the DeepSeek LLM API (user-supplied key) with a structured 3-step research pipeline for finding latest versions and generating update advice.

All scanning is plugin-based — the built-in `applications`, `homebrew`, and `npm` scanners implement the `ScannerPlugin` trait.

Frais is **not an AI agent**. It is a deterministic command-line tool: each command does one
thing and exits. The `--json` output provides structured data that external tools can consume.

## Commands

```bash
# Build (debug)
cargo build

# Build (release)
cargo build --release

# Run the CLI
cargo run -- doctor
cargo run -- advise
cargo run -- advise --all
cargo run -- advise -j 5

# Run all tests
cargo test

# Run a single test
cargo test test_doctor_json_output

# Install binary
bash scripts/install_frais.sh

# Test the built binary
./target/release/frais doctor
./target/release/frais plugins list
```

## Architecture

```
src/
  main.rs                # Entry point — clap CLI app assembly
  lib.rs                 # Library root for integration tests
  models.rs              # Serde structs: SystemProfile, SoftwareItem, UpdateCandidate,
                         #   PluginScanResult, ScanResult, ResearchResult, dependency_impact
  providers.rs           # Provider/ModelInfo structs; DeepSeek provider definition
  store/                 # Persistent storage layer
    mod.rs               #   Module re-exports
    config_store.rs      #   ProviderConfig + config.toml CRUD, env var overrides
    plugin_store.rs      #   Plugin state: reads/writes plugins.toml
    ignore_store.rs      #   Ignore list: ignore.txt CRUD
    scan_cache.rs        #   Atomic last_advice.json cache writes
  llm/                   # LLM client layer (multi-protocol, per-provider)
    mod.rs               #   CLIENT_MAP registry + get_client() factory
    base.rs              #   LLMClient trait + LLMRequestError
    openai_compat.rs     #   OpenAICompatibleClient base (Bearer auth, /v1/chat/completions)
    deepseek.rs          #   DeepSeekOpenAIClient + DeepSeekAnthropicClient
    mimo.rs              #   MiMoClient (Xiaomi MiMo, max_completion_tokens)
  coordinator.rs         # Orchestration: select_plugins, run_scan, run_summaries
  web_tools.rs           # Web tools: web_search (DDGS), web_search_strategy (provider→DDGS fallback),
                         #   web_fetch, web_fetch_batch
  system.rs              # macOS detection (sw_vers, uname -m)
  paths.rs               # Shared runtime paths (~/.frais/...)
  logging_config.rs      # flexi_logger setup with file rotation
  ignore_filter.rs       # Applies ignore.txt to ScanResult (matches Python's ignore_filter.py)
  cli/                   # CLI command implementations
    mod.rs               #   Clap args structs + command dispatch
    output.rs            #   print_json_success() + exit_with_error() — shared JSON/CLI output helpers
    signal.rs            #   install_interrupt_handler() — SIGINT handler for scan/advise
    scan_progress.rs     #   indicatif Progress bar rendering (matches Python's ui/scan_progress.py)
    doctor.rs            #   doctor command
    config.rs            #   config commands: manage, show, path, test
    ignore.rs            #   ignore commands: list, add, remove
    plugins_cmd.rs       #   plugins commands: list, enable, disable
    scan.rs              #   scan command
    advise.rs            #   advise command (scan + summaries)
    summarize.rs         #   summarize <id> command
    update.rs            #   update command
  plugins/               # Plugin system
    mod.rs               #   ScannerPlugin trait + build_summary_prompt() + SUMMARIZE_PROMPT
    registry.rs          #   Static plugin registry via linkme distributed_slice
    subprocess_json.rs   #   Shared helper: run_json() with DYLD_LIBRARY_PATH isolation
    applications/        #   ApplicationsPlugin
      mod.rs             #     Re-exports
      plugin.rs          #     ApplicationsPlugin impl
      discovery.rs       #     scan_applications, read_application (Info.plist parsing)
      source_classifier.rs #   classify_source (codesign + xattr based)
      app_store.rs       #     iTunes API (check_app_store_version, resolve_app_store_command)
      research/          #     LLM 3-step pipeline
        mod.rs           #       Re-exports
        pipeline.rs      #       research_application_update, llm_structured_research
        prompts.rs       #       SEARCH_QUERIES_PROMPT, PICK_URLS_PROMPT, EXTRACT_VERSION_PROMPT
        json_parser.rs   #       parse_json_list, parse_json_object, ensure_list
        candidate_factory.rs #   make_candidate
        version_compare.rs   #   is_newer, normalize version comparison
    homebrew/            #   HomebrewPlugin
      mod.rs             #     Re-exports
      plugin.rs          #     HomebrewPlugin + brew_info, brew_uses, _first helpers
    npm/                 #   NpmPlugin
      mod.rs             #     Re-exports
      plugin.rs          #     NpmPlugin + make_candidate
```

Design principle: all functionality is plugin-based. The CLI provides `plugins`, `config`, `ignore`, `doctor`. Commands with `--json` output (`scan`, `summarize`) are designed for consumption by external LLM agents. `update` is interactive. `advise` is a convenience command = scan + summaries + display. Each plugin owns its entire scan pipeline internally — ApplicationsPlugin does discovery + LLM research; Homebrew/npm do a single step. `--plugins` respects persisted enable/disable state.

## Plugin interface (Rust trait)

```rust
pub trait ScannerPlugin: Send + Sync {
    fn name(&self) -> &'static str;
    fn enabled_by_default(&self) -> bool { false }
    fn display_color(&self) -> &'static str { "white" }
    fn scan_steps(&self) -> &'static [&'static str] { &[] }
    fn is_available(&self) -> bool;

    fn scan(
        &self,
        system: &SystemProfile,
        on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
        max_workers: usize,
    ) -> PluginScanResult;

    fn scan_all(
        &self,
        system: &SystemProfile,
        on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
        max_workers: usize,
    ) -> PluginScanResult {
        self.scan(system, on_progress, max_workers)
    }

    fn update(&self, candidate: &UpdateCandidate) -> bool { /* default: run command */ }

    fn summarize(
        &self,
        agent: &dyn LLMClient,
        candidate: &mut UpdateCandidate,
    ) -> Result<(), LLMRequestError> { /* default: Chinese prompt via build_summary_prompt() */ }
}
```

Plugins are registered via `linkme::distributed_slice` in each plugin's `mod.rs`:
```rust
#[linkme::distributed_slice(crate::plugins::registry::PLUGINS)]
static PLUGIN: fn() -> (&'static str, Box<dyn ScannerPlugin>) = ...;
```

## PluginScanResult / ScanResult (serde)

```rust
#[derive(Serialize, Deserialize)]
pub struct PluginScanResult {
    pub items: Vec<SoftwareItem>,
    pub candidates: Vec<UpdateCandidate>,
    pub skipped: Vec<String>,
}

#[derive(Serialize, Deserialize)]
pub struct ScanResult {
    pub system: SystemProfile,
    pub plugin_results: BTreeMap<String, PluginScanResult>,
}
```

## Concurrency model

Two layers of concurrency:

1. **Scan layer**: `coordinator::run_scan()` — all plugins scan concurrently via `std::thread::scope`. Each plugin owns internal concurrency (ApplicationsPlugin uses `rayon::ThreadPool` for parallel LLM research; Homebrew/npm do a single subprocess call). Progress driven by `on_progress(step, done, total)` callback which is `Sync` so it can be called from worker threads.
2. **Summary layer**: `coordinator::run_summaries()` — `plugin.summarize()` called via `rayon::par_iter()` for all candidates in parallel.

## Progress bar

`cli/scan_progress.rs` uses `indicatif::MultiProgress` with per-plugin progress bars. Each plugin gets one bar labeled with its `scan_steps`. The `on_progress` callback updates the bar's message and position. A dedicated SummaryBar tracks summary generation progress. After all scans, total time (= max scan time + summarize time) is printed.

## Research flow (ApplicationsPlugin-private)

The LLM 3-step research pipeline lives in `plugins/applications/research/` — an internal implementation detail of `ApplicationsPlugin.scan()`. All items (App Store and non-App Store) go through `research_application_update()`:

- **App Store items** → iTunes API fast path (~1s per item)
- **Non-App Store items** → LLM 3-step structured research:

1. **Generate queries**: LLM produces 2-3 search queries for the app. All queries executed in parallel via `web_search_strategy` — uses provider server-side search when available (DeepSeek Anthropic), falls back to DDGS otherwise.
2. **Pick URLs**: LLM analyzes deduplicated search results and picks the top 3-5 most promising URLs.
3. **Extract version**: All picked URLs fetched via `web_fetch_batch`. LLM parses the content and returns version info (JSON with confidence level).

Plugins that don't need research (Homebrew, npm) skip the LLM pipeline entirely — they know the latest version from their package manager.

## Data flow

**`advise` command**:
1. `coordinator::select_plugins()` (respects `--plugins`, persisted enable/disable state)
2. `coordinator::run_scan()` — concurrent scans with indicatif progress. Each plugin owns its internal steps.
3. `ignore_filter::apply_ignore_filter()` — removes ignored items/candidates
4. `coordinator::run_summaries()` — `plugin.summarize()` for each candidate via rayon
5. Display + save cache atomically

**`scan` command** (`--json` output for external LLM consumption):
1. Same scan as advise step 2-3
2. Saves cache for `summarize`/`update` to consume
3. Displays result (no summaries)

**`summarize <id>`**:
1. Loads cached scan result, finds candidate by item_id
2. Calls `plugin.summarize()`, writes `ai_summary` back to cache atomically
3. Prints result (Markdown rendered via `termimad::MadSkin`)

**`update [id]`**:
1. Loads cache, parses candidates, filters by exact id/name match
2. For each candidate: display info + AI Analysis → Proceed? → `plugin.update()`

## JSON output formats

All commands that support `--json` follow a unified **LLM Agent Contract**: the JSON output is designed so an external LLM can consume it deterministically.

### Universal envelope

```json
// Success — ok is always true, always the first key:
{"ok": true, ...command-specific fields}

// Error — ok is always false, error then reason then hint then context fields:
{"ok": false, "error": "<what happened>", "reason": "<stable enum>", "hint": "<what to do next>", ...context}
```

**Invariants** (guaranteed across all commands, all versions):

1. `ok` is always the first key and always a boolean.
2. On error, `error` is always the second key, `reason` is always the third (stable machine enum), `hint` is always the fourth.
3. Additional context keys (`item_id`, `plugin_name`, `requested`) carry structured data for LLM branching.
4. Exit code `0` = success. Exit code `1` = general error. Exit code `2` = config/parameter error.
5. `null` always means "not yet computed".
6. Empty list `[]` means "checked and found nothing".
7. **IDs round-trip**: an `id` from `scan --json` is a valid argument to `summarize <id>` and `update <id>`.
8. Enum values are lowercased stable strings.

### Error reasons (stable enum)

| `reason` | Meaning | Commands that return it |
|----------|---------|------------------------|
| `config_missing` | No LLM provider configured | advise, summarize, config test |
| `connection_error` | LLM connection failed | config test, summarize |
| `no_plugins_matched` | All requested plugins unavailable or disabled | scan, advise |
| `unknown_plugin` | Plugin name not in registry | plugins enable, plugins disable |
| `plugin_not_found` | Plugin from cache no longer installed | summarize |
| `no_cache` | No scan cache file exists | summarize |
| `cache_read_error` | Cache file exists but is corrupt | summarize |
| `candidate_not_found` | ID not in cached scan results | summarize |

### Shared helpers (`cli/output.rs`)

- `print_json_success(extra: BTreeMap<String, Value>)` — prints `{"ok": true, ...extra}` to stdout. The `ok` key is reserved.
- `exit_with_error(message, json_mode, exit_code, reason, hint, extra)` — in JSON mode prints error envelope to stdout then `process::exit(code)`. In CLI mode prints red error text to stderr then exits.

### Command contract summary

| Command | Precondition | Key success fields | Error reasons | Next command |
|---------|-------------|-------------------|---------------|--------------|
| `doctor --json` | none | `version`, `system`, `plugins.<name>.available`, `llm.configured` | (none) | `config manage` if `!llm.configured` |
| `config show --json` | none | `configured`, `provider`, `key_source` | (none) | `config test` to verify |
| `config test --json` | config exists | `provider`, `model`, `url`, `response` | `config_missing`, `connection_error` | `scan` or `advise` |
| `config path --json` | none | `path` | (none) | — |
| `plugins list --json` | none | `plugins[].name`, `.available`, `.effective` | (none) | `plugins enable/disable <name>` |
| `plugins enable/disable --json <name>` | plugin exists | `plugin`, `action` | `unknown_plugin` | `plugins list` to verify |
| `ignore list --json` | none | `ignored[]`, `count` | (none) | `ignore add/remove <id>` |
| `ignore add/remove --json <id>` | none | `app_id`, `action` | (none) | `ignore list` to verify |
| `scan --json` | LLM optional | `plugin_results.<plugin>.items[]`, `.candidates[]` | `no_plugins_matched` | `summarize <id>` or `update <id>` |
| `advise --json` | LLM configured | same as `scan` + `ai_summary` populated | `config_missing`, `no_plugins_matched` | `update <id>` |
| `summarize --json <id>` | cache exists | `item_id`, `ai_summary` | `no_cache`, `cache_read_error`, `candidate_not_found`, `plugin_not_found`, `config_missing` | `update <id>` |

## Key patterns

- **Provider registry**: Providers defined in `providers.rs` as `Provider` structs with `ModelInfo` entries (`supports_thinking` flag). Configuration stored as `[llm]` TOML in `config.toml`. `FRAIS_LLM_API_KEY` env var overrides the file-stored key. API keys are never logged.
- **LLM client layer**: `llm/` package — protocol-agnostic trait (`LLMClient`) with `OpenAICompatibleClient` as the OpenAI-protocol base. Factory `get_client(config, protocol)` selects by `(provider_id, protocol)` from `CLIENT_MAP`. Each provider subclass injects thinking control via its own mechanism (`extra_body` for OpenAI, `thinking` param for Anthropic).
- **JSON/CLI output**: `cli/output.rs` provides `print_json_success()` and `exit_with_error()`. Every command uses these two helpers — errors are a single function call with no branching.
- **Testing**: 24 integration tests in `tests/cli_integration_test.rs` using `assert_cmd` and `predicates`. Unit tests inline with `#[cfg(test)] mod tests` in each module.
- **Version comparison**: Uses `semver` crate; strips leading `v`/`V` before comparing.
- **Source classification**: Applications are classified as AppStore, LocalBuild, NetworkDownload, Application, or Unknown based on `codesign` authority, team ID, and `xattr` quarantine data.
- **Structured LLM pipeline**: 3 discrete LLM calls per app (not tool-calling / agentic). Each call returns structured JSON. Prompt constants in `plugins/applications/research/prompts.rs`.
- **Logging**: `--verbose` sets INFO, `--debug` sets DEBUG. Logs go to stderr and `~/.frais/log/frais.log` by default. `--log-file` overrides path, `--no-log` disables file logging. Auto-rotation at 50MB via `flexi_logger`.
- **Progress bar**: `indicatif::MultiProgress` with per-plugin progress bars. Total time = max(scan times) + summarize time.
- **Ignore list**: `~/.frais/config/ignore.txt` stores app IDs to skip. Managed via `frais ignore add/remove/list`. Filtered after scan by `ignore_filter.rs`.
- **Plugin registry**: Static registration via `linkme::distributed_slice`. Built-in plugins (applications, homebrew, npm) are always present.
- **Atomic writes**: All config and state files written to `.tmp` sibling then atomically renamed via `std::fs::rename()`.
- **Subprocess env isolation**: All subprocess calls clear `DYLD_LIBRARY_PATH` from the child environment.
- **Ctrl+C handling**: `cli/signal.rs` uses `libc::signal(SIGINT)` with a handler that restores cursor visibility (`\033[?25h`) and calls `libc::_exit(130)`. The handler only uses async-signal-safe functions.
- **Markdown rendering**: CLI output uses `termimad::MadSkin` to render Markdown (`ai_summary`) in the terminal, matching Python's `rich.markdown.Markdown`.
