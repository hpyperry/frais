# Frais

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Coverage](https://img.shields.io/badge/coverage-72%25-green)](https://github.com/hpyperry/frais)

macOS update checker CLI with LLM-powered version research. Three-layer architecture: **scan** (plugin-based) → **research** (structured LLM pipeline, optional) → **update** (plugin-provided).

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
User  ──▶  CLI (cli.py)  ──▶  Scan (plugins/)  ──▶  Research (plugin-private)  ──▶  Update (plugins/)
         Pure dispatcher        │                              │
                                │  applications/               │  applications/_store.py (iTunes)
                                │  homebrew/                   │  applications/_research.py (LLM)
                                │  npm/                        │  homebrew/npm skip research
                                │                              │
                           PluginScanResult              UpdateCandidate
```

**Scan layer** — each plugin discovers installed software via its own `scan()` / `scan_all()` methods. Homebrew and NPM plugins can directly identify outdated packages from their package managers.

**Research layer** (plugin-private) — only `ApplicationsPlugin` overrides `research()`. It uses a structured 3-step LLM pipeline: generate search queries → pick best URLs → extract version. App Store apps use the iTunes API directly (~1s). Both the iTunes fast path (`applications/_store.py`) and the LLM pipeline (`applications/_research.py`) are private to the applications plugin — they are not general infrastructure.

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
frais advise --apps-only
frais advise -j 5
frais advise --json
```

Scans enabled plugins, researches latest versions, and generates Chinese-language AI summaries. Progress is shown with a live progress bar — one row per plugin.

| Flag | Effect |
|------|--------|
| `--all` | Show all installed software including up-to-date items |
| `--apps-only` | Skip package manager plugins (Homebrew, NPM) |
| `--json` | Machine-readable output |
| `-j N` | Concurrency limit (default 10, max 20) |

### `config`

```bash
frais config              # show current config (redacted)
frais config manage       # interactive provider setup
frais config show         # same as bare `frais config`
frais config path         # print config file path
frais config test         # send a minimal LLM request to validate
```

`show` never prints the full API key — only a 4-character suffix. `test` prints the effective chat-completions URL without revealing the key.

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

Any Python package can register a plugin via entry points. Subclass `ScannerPlugin` and declare an entry point in `frais.plugins`:

```python
from frais.plugins import ScannerPlugin
from frais.models import PluginScanResult, SystemProfile, SoftwareItem, UpdateCandidate

class MyPlugin(ScannerPlugin):
    name = "my-manager"
    enabled_by_default = True

    def is_available(self) -> bool:
        return True  # check if the package manager is installed

    def scan(self, system: SystemProfile) -> PluginScanResult:
        items = [...]  # discover SoftwareItem objects
        return PluginScanResult(items=items, candidates=[], skipped=[])

    def scan_all(self, system: SystemProfile) -> PluginScanResult:
        """Return ALL installed items. Used when --all is passed."""
        return self.scan(system)

    def research(self, llm, item: SoftwareItem) -> UpdateCandidate | None:
        """Optional: research latest version via LLM. Return None if not needed."""
        return None

    def update(self, candidate: UpdateCandidate) -> bool:
        """Optional: execute the update. Default runs candidate.command."""
        return super().update(candidate)

    def summarize(self, llm, candidate: UpdateCandidate) -> str | None:
        """Optional: custom summary logic. Default uses LLM."""
        return llm.summarize_candidate(candidate)
```

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
