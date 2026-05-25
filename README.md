# Frais

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Coverage](https://img.shields.io/badge/coverage-79%25-green)](https://github.com/hpyperry/frais)


Frais is a **traditional CLI tool enhanced with LLM**, not an AI agent. It cannot orchestrate
multi-step tasks, call external tools autonomously, or maintain conversational context.
The `--json` output provides structured, machine-readable data that can be consumed
by external tools — build a GUI, feed results to another program, or integrate with
an LLM-based workflow. Full Agent-mode / MCP Server support requires a significant
architectural rewrite and is not available today.

## Quick start

```bash
uv sync --extra dev
uv run frais doctor
uv run frais config manage
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

User       ──▶ frais advise                   (scan + summarize + Rich UI)
                frais update                   (interactive execution)
                frais config manage            (interactive setup)
                frais plugins enable/disable   (plugin management)

Internal:
  cli.py assembles Typer commands
  commands/ ──▶ coordinator.py ──▶ plugins/
  store/ handles config, plugin state, ignore list, and scan cache
  web_tools.py handles search (DDGS + provider web_search strategy) and fetch for application research
```

**Scan layer** — each plugin discovers installed software via its own `scan()` / `scan_all()` methods. Homebrew and NPM plugins can directly identify outdated packages from their package managers.

**Research layer** (plugin-private) — `ApplicationsPlugin.scan()` internally runs a structured 3-step LLM pipeline: generate search queries → pick best URLs → extract version. Web search uses `web_search_strategy()` which calls the provider's server-side search when available (DeepSeek Anthropic), falling back to DDGS otherwise. App Store apps skip this entirely and use the iTunes API directly (~1s). Both the iTunes fast path (`applications/app_store.py`) and the LLM pipeline (`applications/research/`) are private to the applications plugin. Summaries are generated via `plugin.summarize()` per-candidate.

**Update layer** — each plugin provides its own `update()` method. Homebrew runs `brew upgrade`, NPM runs `npm install -g`, and Applications resolve App Store deep links or prompt to open the `.app` bundle.

## Commands

All commands that accept `--json` follow a unified **LLM Agent Contract**: success `{"ok": true, ...}`, error `{"ok": false, "error": "...", "reason": "<enum>", "hint": "..."}`. The `reason` field is a stable machine-readable enum that an LLM agent can branch on deterministically; the `hint` field tells the agent what action to take next. IDs round-trip between commands (scan → summarize → update). Without `--json`, commands emit Rich-formatted terminal output. See [CLAUDE.md](./CLAUDE.md) for the full contract specification.

### `doctor`

```bash
frais doctor
frais doctor --json
```

Read-only system check. Prints macOS version, architecture, Applications paths, plugin availability, and redacted LLM provider status.

`--json` output:

```json
{
  "ok": true,
  "system": {
    "os_name": "macOS",            // OS display name
    "os_version": "26.5",          // OS version string
    "arch": "arm64",               // CPU architecture (arm64 / x86_64)
    "applications_paths": ["/Applications", "~/Applications"]
  },
  "plugins": {
    "<name>": {
      "available": "yes",          // "yes" if underlying tool is installed, "no" otherwise
      "default": "enabled"         // Plugin's enabled_by_default setting
    }
  },
  "llm": null | {
    "configured": true,            // true if provider + model + key are all set
    "provider": "deepseek",        // Provider id string
    "model": "deepseek-v4-flash",  // Model id string
    "key_suffix": "***abcd"        // Last 4 characters of API key, masked
  }
}
```

### `advise`

```bash
frais advise
frais advise --all
frais advise --plugins homebrew,npm
frais advise -j 5
frais advise --json
```

Scans enabled plugins, researches latest versions (via LLM for Applications, via package manager for Homebrew/npm), generates AI summaries, and displays results. Requires a configured LLM provider. Progress is shown with a live Rich progress bar — one row per plugin, independent per-task timers.

| Flag | Effect |
|------|--------|
| `--all` | Show all installed software including up-to-date items |
| `--plugins NAMES` | Comma-separated plugin names to advise on |
| `--json` | Machine-readable JSON (for agent consumption) |
| `-j N` | Concurrency limit for LLM requests (default 10, max 20) |

`--json` output: same format as `scan --json` (see below). The only difference is that `ai_summary` fields are populated — `advise` runs summaries, `scan` does not.

### `scan`

```bash
frais scan
frais scan --plugins applications
frais scan --all
frais scan --json
```

Same scan logic as `advise` but without AI summaries. Saves cache to `~/.frais/log/last_advice.json` for `summarize` and `update` to consume later.

| Flag | Effect |
|------|--------|
| `--all` | Show all installed software including up-to-date items |
| `--plugins NAMES` | Comma-separated plugin names to scan |
| `--json` | Machine-readable JSON (for agent consumption) |

`--json` output (same format for both `scan --json` and `advise --json`):

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
          "id": "com.google.Chrome",       // Unique ID; bare bundle ID, "brew:<name>", or "npm:<name>"
          "name": "Google Chrome",         // Display name
          "kind": "application",           // App kind (application, formula, cask, npm package, etc.)
          "source": "network download",    // SourceKind enum: application | local build | network download | app store | brew | brew cask | npm | unknown
          "current_version": "131.0.6778.265",
          "path": "/Applications/Google Chrome.app",
          "metadata": {}                   // Plugin-specific data (bundle_identifier, formula name, etc.)
        }
      ],
      "candidates": [
        {
          "item": { ... },                 // SoftwareItem (same structure as above, minus metadata)
          "latest_version": "132.0.6834.210",
          "release_notes": null,           // Release notes text (may be null)
          "dependency_impact": {
            "used_by": [],                 // Reverse dependencies (brew uses / npm dependents)
            "depends_on": [],              // Forward dependencies
            "impact_level": "unknown"      // unknown | low | medium | high
          },
          "risk_level": "low",             // low | medium | high | unknown
          "ai_summary": "## What's New\n...",  // LLM-generated Markdown summary (null before summarize)
          "recommended_action": "Update",      // Human-readable action: Update | No action | Manual | etc.
          "can_auto_update": true,              // true if plugin.update() with candidate.command will work
          "command": ["brew", "upgrade", "google-chrome"],  // Shell command (empty if not auto-updatable)
          "evidence": ["https://..."]       // URLs that sourced the version info
        }
      ],
      "skipped": ["reason string"]         // Items or errors that were skipped during scan
    }
  }
}
```

**Field notes for agent consumers:**
- `item.id`: globally unique identifier. Bare bundle ID = Application. `brew:` prefix = Homebrew. `npm:` prefix = npm global package.
- `item.source`: how the software was installed. Determines update strategy (App Store → deep link, brew → `brew upgrade`, npm → `npm install -g`).
- `candidate.can_auto_update`: when `true`, the `command` list is safe to run as a subprocess.
- `candidate.ai_summary`: `null` in `scan --json` output (summaries haven't run). Populated in `advise --json` or after running `frais summarize <id>`.
- `candidate.recommended_action` values seen in practice: `"Update"`, `"No action"`, `"Manual update"`, `"Reinstall from source"`.
- `candidate.risk_level`: LLM-assessed upgrade risk. `"low"` for patch releases, `"medium"` for minor updates, `"high"` for major versions with breaking changes.
- `candidate.evidence`: the web URLs that were fetched and parsed to determine latest version. Useful for verification.

### `summarize`

```bash
frais summarize com.google.Chrome
frais summarize brew:node --json
```

Generates an AI summary for a single candidate from the last scan cache. Writes the result back to cache so `update` can display it.

`--json` output:

```json
// Success:
{"ok": true, "item_id": "com.google.Chrome", "ai_summary": "## What's New\n..."}

// Error (no cache, bad cache, candidate not found, plugin not found, no config):
{"ok": false, "error": "No candidate found for: com.example.App"}
```

### `config`

```bash
frais config              # show current config (redacted)
frais config show         # same as bare `frais config`
frais config show --json
frais config manage       # interactive setup or modify existing config
frais config path         # print config file path
frais config test         # send a minimal LLM request to validate
frais config test --json
```

`manage` detects an existing config and lets you choose what to modify — provider & model, API key, or full reconfiguration. Press Ctrl+C at any step to cancel without saving. `show` never prints the full API key — only a 4-character suffix. `test` sends a single chat-completions request to verify credentials.

Example config (`~/.frais/config/config.toml`):

```toml
[llm]
provider = "deepseek"
model = "deepseek-v4-flash"
api_key = "sk-..."
protocol = "openai"
url = "https://api.deepseek.com"
```

Supported providers: `deepseek`, `mimo` (Xiaomi MiMo). Run `frais config manage` to configure your API key interactively.

API key resolution order: `FRAIS_LLM_API_KEY` env var → `MIMO_API_KEY` env var → `OPENAI_API_KEY` env var → config file.

**`config show --json`:**

```json
// Not configured:
{"ok": true, "configured": false}

// Configured:
{
  "ok": true,
  "configured": true,
  "provider": "deepseek",                // Provider id
  "model": "deepseek-v4-flash",          // Model id
  "protocol": "openai",                  // API protocol: openai | anthropic
  "url": "https://api.deepseek.com/anthropic", // Endpoint URL for current protocol
  "key_suffix": "***abcd",               // Masked key suffix (null if no key)
  "key_source": "config"                 // Where the key comes from: config | env:FRAIS_LLM_API_KEY | env:MIMO_API_KEY | env:OPENAI_API_KEY
}
```

**`config test --json`:**

```json
// Success:
{
  "ok": true,
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "url": "https://api.deepseek.com/v1/chat/completions",
  "response": "Hello! I'm DeepSeek, ready to help."
}

// Error (no config, connection failure, auth error):
{"ok": false, "error": "connection failed: timeout"}
```

`config path --json`:

```json
{"ok": true, "path": "/Users/hpy/.frais/config/config.toml"}
```

`config manage` is interactive only — `--json` is not supported.

### `update`

```bash
frais update
frais update npm
```

Interactive only — no `--json` support. Loads results from the last `frais advise` run, shows each candidate with AI advice, and asks for confirmation. Delegates to each plugin's `update()` method for execution.

### `plugins`

```bash
frais plugins                 # list (same as `frais plugins list`)
frais plugins --json
frais plugins list
frais plugins list --json
frais plugins enable homebrew
frais plugins enable --json homebrew
frais plugins disable homebrew
frais plugins disable --json homebrew
```

Lists and manages plugins. State is persisted to `~/.frais/config/plugins.toml`.

**`plugins list --json`:**

```json
{
  "ok": true,
  "plugins": [
    {
      "name": "applications",     // Plugin name (entry point name)
      "available": "yes",         // "yes" if underlying tool is available, "no" otherwise
      "default": "enabled",       // enabled_by_default value
      "effective": "enabled"      // Actual state after persisted enable/disable overrides
    }
  ]
}
```

- **available**: checks whether the underlying tool is installed (e.g. `brew` command exists)
- **default**: the plugin's `enabled_by_default` property — what it would be if never touched
- **effective**: takes persisted config into account. This is what `advise` uses when selecting plugins.

**`plugins enable --json <name>` / `plugins disable --json <name>`:**

```json
// Success:
{"ok": true, "plugin": "homebrew", "action": "enabled"}

// Error:
{"ok": false, "error": "Unknown plugin: nonexistent"}
```

### `ignore`

```bash
frais ignore                      # list (same as `frais ignore list`)
frais ignore --json
frais ignore list
frais ignore list --json
frais ignore add com.example.app
frais ignore add --json com.example.app
frais ignore remove com.example.app
frais ignore remove --json com.example.app
```

Manages an ignore list stored at `~/.frais/config/ignore.txt` (one app ID per line). Ignored apps are excluded from `advise` and `scan` results. All mutating commands use atomic writes (write to `.tmp`, rename).

**`ignore list --json`:**

```json
{
  "ok": true,
  "ignored": ["com.example.app1", "com.example.app2"],  // Sorted list of ignored bundle IDs
  "count": 2                                             // Number of ignored apps
}
```

**`ignore add --json <app_id>` / `ignore remove --json <app_id>`:**

```json
// add:
{"ok": true, "app_id": "com.example.app", "action": "added"}           // new addition
{"ok": true, "app_id": "com.example.app", "action": "already_ignored"} // already in list

// remove:
{"ok": true, "app_id": "com.example.app", "action": "removed"}       // was in list, now removed
{"ok": true, "app_id": "com.example.app", "action": "not_in_list"}   // wasn't in the list
```

## Writing plugins

Any Python package can register a plugin via entry points. Subclass `ScannerPlugin` and declare an entry point in `frais.plugins`.

### Minimal plugin (one-step scan)

If your package manager tells you which packages are outdated directly (like Homebrew/npm do), you only need one scan step:

```python
from frais.plugins import ScannerPlugin
from frais.models import PluginScanResult, SoftwareItem, SystemProfile, UpdateCandidate

class MyPlugin(ScannerPlugin):
    name = "my-manager"
    enabled_by_default = True
    scan_steps = ["checking outdated packages"]

    def is_available(self) -> bool:
        return True  # check if the tool is installed

    def scan(self, system, on_progress=None, max_workers=10) -> PluginScanResult:
        items = [...]          # discover SoftwareItem objects
        candidates = [...]     # build UpdateCandidate for outdated ones
        if on_progress:
            on_progress(0, len(items), len(items))
        return PluginScanResult(items=items, candidates=candidates, skipped=[])

    def update(self, candidate: UpdateCandidate) -> bool:
        """Default: subprocess.run(candidate.command). Override for custom logic."""
        return super().update(candidate)

    # summarize() uses the default (LLM-generated Chinese summary).
    # Override it for custom summary formatting.
```

### Multi-step plugin (with internal research)

If discovering versions requires extra work (like ApplicationsPlugin does with LLM), declare multiple steps and report progress for each:

```python
class MyPlugin(ScannerPlugin):
    scan_steps = ["discovering items", "researching latest versions"]

    def scan(self, system, on_progress=None, max_workers=10) -> PluginScanResult:
        # Step 1: discover
        items = [...]
        if on_progress:
            on_progress(0, len(items), len(items))

        # Step 2: research — plugin owns its concurrency
        candidates = []
        if on_progress:
            on_progress(1, 0, len(items))  # show step 2 immediately
        for i, item in enumerate(items):
            cand = self._research_one(item)
            if cand:
                candidates.append(cand)
            if on_progress:
                on_progress(1, i + 1, len(items))

        return PluginScanResult(items=items, candidates=candidates)
```

CLI progress bars automatically render `scan_steps` names and advance with `on_progress(step, done, total)`.

### Data model reference

| Model | Key fields | Purpose |
|-------|-----------|---------|
| `SoftwareItem` | `id, name, kind, source, current_version, path, metadata` | One installed piece of software |
| `UpdateCandidate` | `item, latest_version, can_auto_update, command, risk_level, ai_summary, evidence` | A software that has an available update |
| `PluginScanResult` | `items, candidates, skipped` | The output of one plugin's scan |
| `SourceKind` (enum) | `APPLICATION, APP_STORE, LOCAL_BUILD, NETWORK_DOWNLOAD, HOMEBREW_FORMULA, HOMEBREW_CASK, NPM_GLOBAL, UNKNOWN` | How the software was installed |

### Cache format

Both `frais advise` and `frais scan` write to `~/.frais/log/last_advice.json`. The cache is a `ScanResult` serialized to JSON — used by `frais update` and `frais summarize`:

```json
{
  "system": {"os_name": "macOS", "os_version": "26.5", "arch": "arm64",
             "applications_paths": ["/Applications", "~/Applications"]},
  "plugin_results": {
    "<plugin_name>": {
      "items": [
        {"id": "...", "name": "...", "kind": "...", "source": "...",
         "current_version": "...", "path": "...", "metadata": {...}}
      ],
      "candidates": [
        {"item": {...}, "latest_version": "...", "ai_summary": "...",
         "recommended_action": "Update", "can_auto_update": true,
         "command": ["brew", "upgrade", "..."], "risk_level": "low",
         "evidence": ["https://..."]}
      ],
      "skipped": ["reason"]
    }
  }
}
```

`frais scan --json` and `frais advise --json` wrap the same `ScanResult` structure in a `{"ok": true, ...}` envelope. All other `--json` commands use the same envelope pattern — see each command's section above for field descriptions.

### Registration

In your `pyproject.toml`:

```toml
[project.entry-points."frais.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

After installing your package, `frais plugins list` will show it.

## Logs

```bash
frais --debug advise         # DEBUG level logging (includes LLM traces)
frais --log-file ./my.log advise
frais --no-log advise        # disable file logging
```

Logs are written to `~/.frais/log/frais.log` by default. Log files auto-truncate at 5 MB.

## Testing

```bash
uv run pytest
uv run pytest --cov=src/frais --cov-report=term-missing tests/
uv run pytest --cov=src/frais --cov-report=html tests/ && open htmlcov/index.html
```

Tests use `monkeypatch` for all external dependencies — no real HTTP calls or subprocess execution.

## Build a macOS binary

```bash
uv run --extra build python scripts/build_binary.py
dist/frais/frais doctor
```

Uses PyInstaller `--onedir` mode for fast startup. First-run install via `frais.sh` copies to `~/.frais/bin/`:

```bash
bash frais.sh doctor          # auto-installs to ~/.frais/bin/, then runs
~/.frais/bin/frais doctor     # instant after first install
```

The binary contains no API keys or secrets. LLM access uses the provider config in `~/.frais/config/config.toml`.
