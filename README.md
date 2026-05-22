# Frais

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Coverage](https://img.shields.io/badge/coverage-79%25-green)](https://github.com/hpyperry/frais)

macOS update checker CLI with LLM-powered version research. Three-phase pipeline: **scan** (plugin-based discovery + optional LLM research) → **summarize** (AI-generated update advice) → **update** (plugin-provided execution).

Supports 7 curated LLM providers (DeepSeek, OpenAI, Kimi, Grok, Mistral, Qwen, Zhipu) with automatic thinking-mode control.

## Quick start

```bash
uv sync --extra dev
uv run frais doctor
uv run frais config manage
```

LLM features require user-owned configuration in `~/.frais/config/config.toml`. The project never ships or creates a server-side API key. Run `frais config manage` for interactive setup — no manual file editing needed.

## Architecture

```
Agent LLM ──▶ frais scan --json           (structured output)
              frais summarize <id> --json  (single summary)

User     ──▶ frais advise                 (scan + summarize + Rich UI)
              frais update                 (interactive execution)

Internal:
  CLI  ──▶ coordinator.py  ──▶ plugins/
           select_plugins        applications/  (discover → research)
           run_scan              homebrew/      (brew outdated)
           run_summaries         npm/           (npm outdated)
```

**Scan layer** — each plugin discovers installed software via its own `scan()` / `scan_all()` methods. Homebrew and NPM plugins can directly identify outdated packages from their package managers.

**Research layer** (plugin-private) — `ApplicationsPlugin.scan()` internally runs a structured 3-step LLM pipeline: generate search queries → pick best URLs → extract version. App Store apps use the iTunes API directly (~1s). Both the iTunes fast path (`applications/_store.py`) and the LLM pipeline (`applications/_research.py`) are private to the applications plugin. Summaries are generated via `plugin.summarize()` per-candidate.

**Update layer** — each plugin provides its own `update()` method. Homebrew runs `brew upgrade`, NPM runs `npm install -g`, and Applications resolve App Store deep links or prompt to open the `.app` bundle.

## Commands

### `doctor`

```bash
frais doctor
```

Prints macOS version, architecture, Applications paths, plugin availability, and redacted LLM provider status. Read-only, safe to run before any configuration.

### `advise`

```bash
frais advise
frais advise --all
frais advise --plugins homebrew,npm
frais advise -j 5
frais advise --json
```

Scans enabled plugins, researches latest versions, generates AI summaries, and displays results. Progress is shown with a live Rich progress bar — one row per plugin, independent per-task timers. Displays AI Analysis alongside each update candidate.

| Flag | Effect |
|------|--------|
| `--all` | Show all installed software including up-to-date items |
| `--plugins NAMES` | Comma-separated plugin names to advise on |
| `--json` | Machine-readable JSON (for agent consumption) |
| `-j N` | Concurrency limit (default 10, max 20) |

### `scan`

```bash
frais scan
frais scan --plugins applications
frais scan --all
frais scan --json
```

Same scan logic as `advise` without summaries. JSON output is suitable for external agent LLM consumption. Saves cache for `summarize` and `update` to consume later.

### `summarize`

```bash
frais summarize com.google.Chrome
frais summarize brew:node --json
```

Generates an AI summary for a single candidate from the last scan cache. Writes the result back to cache so `update` can display it. Useful for agent workflows: `scan` → pick a candidate → `summarize` → `update`.

### `config`

```bash
frais config              # show current config (redacted)
frais config manage       # interactive setup or modify existing config
frais config show         # same as bare `frais config`
frais config path         # print config file path
frais config test         # send a minimal LLM request to validate
```

`manage` detects an existing config and lets you choose what to modify — provider & model, API key, or full reconfiguration. Press Ctrl+C at any step to cancel without saving. `show` never prints the full API key — only a 4-character suffix. `test` prints the effective chat-completions URL without revealing the key.

Example config (`~/.frais/config/config.toml`):

```toml
[llm]
provider = "deepseek"
model = "deepseek-v4-flash"
api_key = "sk-..."
```

Supported providers: `deepseek`, `openai`, `kimi`, `grok`, `mistral`, `qwen`, `zhipu`. Each provider offers a curated set of models — run `frais config manage` to browse them interactively.

API key resolution order: `FRAIS_LLM_API_KEY` env var → `OPENAI_API_KEY` env var → config file.

### `update`

```bash
frais update
frais update npm
```

Loads results from the last `frais advise` run, shows each candidate with AI advice, and asks for confirmation. Delegates to each plugin's `update()` method for execution.

### `plugins`

```bash
frais plugins
frais plugins list
frais plugins enable homebrew
frais plugins disable homebrew
```

Lists and manages plugins. State is persisted to `~/.frais/config/plugins.toml`. Disabled plugins are skipped during `advise`.

### `ignore`

```bash
frais ignore
frais ignore list
frais ignore add com.example.app
frais ignore remove com.example.app
```

Manages an ignore list stored at `~/.frais/config/ignore.txt` (one app ID per line). Ignored apps are excluded from `advise` runs.

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

`frais scan --json` and `frais advise --json` output the same format for agent LLM consumption.

### Registration

In your `pyproject.toml`:

```toml
[project.entry-points."frais.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

After installing your package, `frais plugins list` will show it.

## Logs

```bash
frais --verbose advise       # INFO to stderr
frais --debug advise         # DEBUG to stderr (includes LLM traces)
frais --log-file ./my.log advise
frais --no-log advise        # disable file logging
```

Logs are written to both stderr and `~/.frais/log/frais.log` by default. Log files auto-truncate at 5 MB.

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
./dist/frais doctor
```

Built with PyInstaller. The binary contains no API keys or secrets. LLM access uses the provider config in `~/.frais/config/config.toml`.
