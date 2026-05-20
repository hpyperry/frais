# CheckUpgrade

CheckUpgrade is a macOS BYOK CLI that scans installed Applications and Homebrew packages for available updates. It uses an OpenAI-compatible LLM (user-supplied key) with tool calling to research latest versions and generate update advice.

## Quick start

```bash
uv sync --extra dev
uv run checkupgrade doctor
uv run checkupgrade config init
```

LLM features require user-owned configuration via environment variables or
`~/.config/checkupgrade/config.toml`. The project never ships or creates a
server-side API key.

## Commands

```bash
checkupgrade doctor
```

Prints detected macOS version, architecture, Applications paths, Homebrew
availability, and redacted BYOK status.

```bash
checkupgrade advise
checkupgrade advise --apps-only
checkupgrade advise -j 5
checkupgrade advise --json
```

Scans Applications and Homebrew, then researches latest versions using a
three-tier strategy:

1. **iTunes API** — instant for App Store apps
2. **GitHub API** — web search + GitHub releases, no LLM needed
3. **LLM tool calling** — fallback using web search and fetch tools

GitHub and LLM paths run concurrently; if GitHub resolves first, the LLM is
skipped. Use `-j` to control concurrency (default 10, max 20).

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
```

Lists available package manager plugins. v1 includes Homebrew only.

## Logs

Use global logging flags before the command name:

```bash
checkupgrade --verbose advise
checkupgrade --debug advise
checkupgrade --debug --log-file ./checkupgrade.log advise
```

Logs are written to stderr by default. `--verbose` shows high-level progress;
`--debug` also includes subprocess command traces and LLM tool call details.

## Build a macOS binary

```bash
uv run --extra build python scripts/build_binary.py
./dist/checkupgrade doctor
```

The binary is built with PyInstaller and writes no secrets into the artifact.
LLM access still uses BYOK runtime configuration from environment variables or
`~/.config/checkupgrade/config.toml`.
