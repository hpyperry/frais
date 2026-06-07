# Frais

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Frais is a **traditional CLI tool enhanced with LLM**, not an AI agent. It cannot orchestrate
multi-step tasks, call external tools autonomously, or maintain conversational context.
The `--json` output provides structured, machine-readable data that can be consumed
by external tools — build a GUI, feed results to another program, or integrate with
an LLM-based workflow.

Built in Rust with `clap`, `reqwest`, `rayon`, and `serde`. macOS only.

## Quick start

```bash
# Build
cargo build --release

# Run
./target/release/frais doctor
./target/release/frais config manage
```

Or install to `~/.frais/bin/`:

```bash
bash scripts/install_frais.sh
frais doctor
```

LLM features require user-owned configuration in `~/.frais/config/config.toml`. The project never ships or creates a server-side API key. Run `frais config manage` for interactive setup — no manual file editing needed.

## Architecture

```
External   ──▶ frais doctor --json           (system readiness)
  tools /       frais config show --json       (redacted config)
  GUI /         frais config test --json       (connection validation)
  scripts       frais config path --json       (config file location)
                frais plugins list --json      (plugin inventory)
                frais ignore list --json       (exclusion list)
                frais scan --json              (structured scan output)
                frais summarize <id> --json    (single AI summary)

User       ──▶ frais advise                   (scan + summarize + terminal UI)
                frais update                   (interactive execution)
                frais config manage            (interactive setup)
                frais plugins enable/disable   (plugin management)

Internal:
  cli/ assembles clap commands
  cli/ ──▶ coordinator.rs ──▶ plugins/
  store/ handles config, plugin state, ignore list, and scan cache
  web_tools.rs handles search (DDGS + provider web_search strategy) and fetch for application research
```

**Scan layer** — each plugin discovers installed software via its `scan()` / `scan_all()` methods. Homebrew and NPM plugins can directly identify outdated packages from their package managers. Plugins scan concurrently via `std::thread::scope`.

**Research layer** (plugin-private) — `ApplicationsPlugin.scan()` runs a structured 3-step LLM pipeline: generate search queries → pick best URLs → extract version. Web search uses `web_search_strategy()` which calls the provider's server-side search when available (DeepSeek Anthropic), falling back to DDGS otherwise. App Store apps use the iTunes API directly (~1s per item). The iTunes fast path (`app_store.rs`) and the LLM pipeline (`research/`) are private to the applications plugin. Research runs in parallel via `rayon::ThreadPool`.

**Update layer** — each plugin provides its own `update()` method. Homebrew runs `brew upgrade`, NPM runs `npm install -g`, and Applications resolve App Store deep links or prompt to open the `.app` bundle.

## Commands

All commands that accept `--json` follow a unified **LLM Agent Contract**: success `{"ok": true, ...}`, error `{"ok": false, "error": "...", "reason": "<enum>", "hint": "..."}`. The `reason` field is a stable machine-readable enum that an LLM agent can branch on deterministically; the `hint` field tells the agent what action to take next. IDs round-trip between commands (scan → summarize → update). Without `--json`, commands emit console-styled terminal output. See [CLAUDE.md](./CLAUDE.md) for the full contract specification.

### `doctor`

```bash
frais doctor
frais doctor --json
```

Shows system info, plugin availability, and LLM configuration status.

### `config`

```bash
frais config manage        # Interactive setup wizard
frais config show --json   # Show provider/model/key_source
frais config test --json   # Validate connection with a test chat
frais config path --json   # Print config file location
```

### `plugins`

```bash
frais plugins list --json
frais plugins enable <name>
frais plugins disable <name>
```

### `ignore`

```bash
frais ignore list --json
frais ignore add <app_id>
frais ignore remove <app_id>
```

### `scan`

```bash
frais scan --json
frais scan --json --plugins applications --all
```

Structured scan output for LLM agent consumption. Includes `system`, `plugin_results` with `items` and `candidates`. Saves cache to `~/.frais/log/last_advice.json` for `summarize` and `update`.

### `advise`

```bash
frais advise
frais advise --all
frais advise --json
frais advise --plugins homebrew,npm -j 5
```

Full pipeline: scan → ignore filter → AI summaries → display. Requires configured LLM provider.

### `summarize`

```bash
frais summarize com.google.Chrome
frais summarize brew:node --json
```

Generate an AI summary for a single candidate from a previous scan/advise.

### `update`

```bash
frais update
frais update brew:node
```

Interactive update execution. Displays candidates, AI analysis, then prompts for confirmation.

## JSON output reference

### Universal envelope

```json
// Success:
{"ok": true, ...command-specific fields}

// Error:
{"ok": false, "error": "<what happened>", "reason": "<stable enum>", "hint": "<what to do next>", ...context}
```

### Error reasons (stable enum)

| `reason` | Meaning | Commands |
|----------|---------|----------|
| `config_missing` | No LLM provider configured | advise, summarize, config test |
| `connection_error` | LLM connection failed | config test, summarize |
| `no_plugins_matched` | All requested plugins unavailable or disabled | scan, advise |
| `unknown_plugin` | Plugin name not in registry | plugins enable/disable |
| `plugin_not_found` | Plugin from cache no longer installed | summarize |
| `no_cache` | No scan cache file exists | summarize |
| `cache_read_error` | Cache file exists but is corrupt | summarize |
| `candidate_not_found` | ID not in cached scan results | summarize |

### `doctor --json`

```json
{
  "ok": true,
  "version": "0.1.0",
  "system": {
    "os_name": "macOS",
    "os_version": "26.5",
    "arch": "arm64",
    "applications_paths": ["/Applications", "~/Applications"]
  },
  "plugins": {
    "<name>": {
      "available": "yes|no",
      "default": "enabled|disabled"
    }
  },
  "llm": null | {
    "configured": true,
    "provider": "DeepSeek",
    "model": "deepseek-v4-flash",
    "protocol": "openai",
    "url": "https://api.deepseek.com/anthropic",
    "key_suffix": "***abcd"
  }
}
```

### `config show --json`

```json
{"ok": true, "configured": false}

// When configured:
{
  "ok": true,
  "configured": true,
  "provider": "DeepSeek",
  "model": "deepseek-v4-flash",
  "key_suffix": "***abcd",
  "key_source": "env:FRAIS_LLM_API_KEY"
}
```

### `config test --json`

```json
// Success:
{"ok": true, "provider": "DeepSeek", "model": "deepseek-v4-flash", "url": "https://api.deepseek.com", "response": "..."}

// Error:
{"ok": false, "error": "...", "reason": "config_missing|connection_error", "hint": "..."}
```

### `config path --json`

```json
{"ok": true, "path": "/Users/.../.frais/config/config.toml"}
```

### `plugins list --json`

```json
{
  "ok": true,
  "plugins": [
    {
      "name": "applications",
      "available": "yes|no",
      "default": "enabled|disabled",
      "effective": "enabled|disabled"
    }
  ]
}
```

### `plugins enable/disable --json <name>`

```json
// Success:
{"ok": true, "plugin": "homebrew", "action": "enabled|disabled"}

// Error:
{"ok": false, "error": "Unknown plugin: <name>", "reason": "unknown_plugin", "hint": "..."}
```

### `ignore list --json`

```json
{
  "ok": true,
  "ignored": ["com.example.app", "npm:example"],
  "count": 2
}
```

### `ignore add/remove --json <app_id>`

```json
// add:
{"ok": true, "app_id": "com.example.app", "action": "added"}
{"ok": true, "app_id": "com.example.app", "action": "already_ignored"}

// remove:
{"ok": true, "app_id": "com.example.app", "action": "removed"}
{"ok": true, "app_id": "com.example.app", "action": "not_in_list"}
```

### `scan --json` / `advise --json`

Both output a serialized `ScanResult` in the success envelope:

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
          "id": "com.google.Chrome",
          "name": "Google Chrome",
          "kind": "application",
          "source": "network download",
          "current_version": "131.0.6778.265",
          "path": "/Applications/Google Chrome.app",
          "metadata": {}
        }
      ],
      "candidates": [
        {
          "item": { "...": "..." },
          "latest_version": "132.0.6834.210",
          "release_notes": null,
          "dependency_impact": {
            "used_by": [],
            "depends_on": [],
            "impact_level": "unknown"
          },
          "risk_level": "low",
          "ai_summary": "## What's New\n...",
          "recommended_action": "Update",
          "can_auto_update": true,
          "command": ["brew", "upgrade", "google-chrome"],
          "evidence": ["https://..."]
        }
      ],
      "skipped": ["reason"]
    }
  }
}
```

### `summarize --json <id>`

```json
// Success:
{"ok": true, "item_id": "com.google.Chrome", "ai_summary": "## What's New\n..."}

// Error:
{"ok": false, "error": "No scan cache found.", "reason": "no_cache", "hint": "..."}
{"ok": false, "error": "No candidate found for: <id>", "reason": "candidate_not_found", "hint": "...", "item_id": "<id>"}
```

## Writing plugins

Plugins implement the `ScannerPlugin` trait and register via `linkme::distributed_slice`.

### Minimal plugin

```rust
use frais_lib::plugins::ScannerPlugin;
use frais_lib::models::{PluginScanResult, SoftwareItem, SystemProfile, UpdateCandidate};

struct MyPlugin;

impl ScannerPlugin for MyPlugin {
    fn name(&self) -> &'static str { "my-manager" }
    fn enabled_by_default(&self) -> bool { true }
    fn scan_steps(&self) -> &'static [&'static str] { &["checking outdated packages"] }
    fn is_available(&self) -> bool { true }

    fn scan(
        &self,
        system: &SystemProfile,
        on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
        max_workers: usize,
    ) -> PluginScanResult {
        // Discover and build items + candidates
        PluginScanResult { items, candidates, skipped: vec![] }
    }
}

// Register:
#[linkme::distributed_slice(frais_lib::plugins::registry::PLUGINS)]
static PLUGIN: fn() -> (&'static str, Box<dyn ScannerPlugin>) = || {
    ("my-manager", Box::new(MyPlugin))
};
```

### Registration

Plugins are discovered at compile time via `linkme::distributed_slice`. Add your plugin module to the build, and its static registration will be picked up automatically. No runtime discovery or config files needed — `frais plugins list` will show it.

## Logs

```bash
frais --debug advise
frais --log-file ./my.log advise
frais --no-log advise
```

Logs are written to `~/.frais/log/frais.log` by default. Log files auto-rotate at 50 MB.

## Testing

```bash
cargo test
cargo test test_doctor_json_output
```

24 integration tests via `assert_cmd` + `predicates`, plus inline unit tests in each module.

## Build

```bash
cargo build --release
./target/release/frais doctor
```

Install to `~/.frais/bin/`:

```bash
bash scripts/install_frais.sh
frais doctor
```

The binary contains no API keys or secrets. LLM access uses the provider config in `~/.frais/config/config.toml`.
