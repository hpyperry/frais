# CheckUpgrade

CheckUpgrade is a macOS BYOK CLI that scans installed Applications, Homebrew, and npm packages for available updates. It uses an OpenAI-compatible LLM (user-supplied key) with a structured research pipeline to find latest versions and generate update advice.

All scanning is plugin-based — the built-in `applications`, `homebrew`, and `npm` scanners are all `ScannerPlugin` implementations.

## Quick start

```bash
uv sync --extra dev
uv run checkupgrade doctor
uv run checkupgrade config init
```

LLM features require user-owned configuration via environment variables or
`~/.checkupgrade/config/config.toml`. The project never ships or creates a
server-side API key.

> **Note**: Thinking/reasoning models (e.g. DeepSeek-R1, o1, o3) are not yet
> supported. The research pipeline requires clean JSON output which thinking
> models do not reliably produce. Use a standard model (e.g. deepseek-chat,
> gpt-4o).

## Commands

```bash
checkupgrade doctor
```

Prints detected macOS version, architecture, Applications paths, plugin
availability, and redacted BYOK status.

```bash
checkupgrade advise
checkupgrade advise --all
checkupgrade advise --apps-only
checkupgrade advise -j 5
checkupgrade advise --json
```

Scans Applications, Homebrew, and npm global packages, then researches latest
versions using a structured 3-step pipeline per app:

1. LLM generates search queries (smarter than hardcoded queries)
2. We search and LLM picks the best 3 URLs
3. We fetch those URLs and LLM extracts the version number

App Store apps use the iTunes API directly (fast, no LLM needed).

Use `--all` to show all installed software including up-to-date items.
Use `--apps-only` to skip package manager plugins.
Use `-j` to control concurrency (default 10, max 20). Progress is shown
with a live progress bar — one row per plugin.

```bash
checkupgrade config
checkupgrade config init
checkupgrade config show
checkupgrade config path
checkupgrade config test
```

Creates or displays BYOK configuration. `show` never prints the full API key.
`test` sends a minimal chat-completions request and prints the effective URL
without revealing the key.

DeepSeek example:

```toml
[llm]
provider = "openai-compatible"
base_url = "https://api.deepseek.com"
model = "deepseek-chat"
api_key = "..."
```

```bash
checkupgrade update
checkupgrade update --only node
```

Shows each auto-updatable candidate and asks for confirmation before running a
command. v1 only auto-executes Homebrew formula/cask updates.

```bash
checkupgrade plugins
checkupgrade plugins list
checkupgrade plugins enable homebrew
checkupgrade plugins disable homebrew
```

Lists and manages plugins. `enable` / `disable` persist the choice to
`~/.checkupgrade/config/plugins.toml`. When a plugin is disabled, it is
skipped during `advise` runs.

### Writing plugins

Any Python package can register a plugin via entry points. Subclass
`ScannerPlugin` and declare an entry point in `checkupgrade.plugins`:

```python
from checkupgrade.plugins import ScannerPlugin
from checkupgrade.models import PluginScanResult, SystemProfile, SoftwareItem, UpdateCandidate

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
        return self.scan(system)  # or return all items

    def research(self, agent, item: SoftwareItem) -> UpdateCandidate | None:
        """Optional: research latest version. Return None if not needed."""
        return None

    def summarize(self, agent, candidate: UpdateCandidate) -> str | None:
        """Optional: custom summary logic."""
        return agent.summarize_candidate(candidate)
```

In your `pyproject.toml`:

```toml
[project.entry-points."checkupgrade.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

After installing your package, `checkupgrade plugins list` will show it.

```bash
checkupgrade ignore
checkupgrade ignore list
checkupgrade ignore add com.example.app
checkupgrade ignore remove com.example.app
```

Manages an ignore list. Ignored apps are excluded from `advise` runs. The list
is stored at `~/.checkupgrade/config/ignore.txt` (one app ID per line).

## Logs

Logs are written to both stderr and `~/.checkupgrade/log/checkupgrade.log` by default.

```bash
checkupgrade --verbose advise
checkupgrade --debug advise
checkupgrade --log-file ./my.log advise
checkupgrade --no-log advise
```

`--verbose` shows high-level progress; `--debug` includes LLM call details and
subprocess traces. Log files auto-truncate at 5MB.

## Build a macOS binary

```bash
uv run --extra build python scripts/build_binary.py
./dist/checkupgrade doctor
```

The binary is built with PyInstaller and writes no secrets into the artifact.
LLM access still uses BYOK runtime configuration from environment variables or
`~/.checkupgrade/config/config.toml`.
