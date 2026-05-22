from __future__ import annotations

import json
import logging
import os
import platform
import signal
import subprocess
from pathlib import Path
from typing import Annotated

import click
import typer
from rich.console import Console
from rich.table import Table

from .config import CONFIG_PATH, load_config, require_config, save_config
from .ignore import add_ignored, load_ignored, remove_ignored
from .models import SourceKind, ScanResult

_DEFAULT_LOG_DIR = Path.home() / ".frais" / "log"
_DEFAULT_LOG_FILE = _DEFAULT_LOG_DIR / "frais.log"
_ADVICE_CACHE = _DEFAULT_LOG_DIR / "last_advice.json"
_LOG_MAX_SIZE = 5 * 1024 * 1024  # 5MB

APP_HELP = """Frais scans macOS Applications, Homebrew packages, and npm global packages for updates.

Default scope:
  - Applications in /Applications and ~/Applications
  - Homebrew formulae and casks when `brew` is available
  - npm global packages when `npm` is available

Safety model:
  - `doctor`, `config`, `plugins`, and `ignore` are read-only.
  - `advise` requires LLM provider configuration via `frais config manage`.
  - `update` auto-executes packages after interactive confirmation.

Common examples:
  frais doctor
  frais config manage
  frais advise
  frais advise -j 5
  frais update
  frais ignore add com.example.app
"""

CONFIG_HELP = """Manage LLM provider configuration.

Frais supports a curated set of OpenAI-compatible providers. Run `frais config manage`
for interactive setup — no manual file editing needed.

Config file:
  ~/.frais/config/config.toml

Environment variable:
  FRAIS_LLM_API_KEY — overrides the API key stored in config

Examples:
  frais config
  frais config show
  frais config manage
  frais config path
  frais config test
"""

PLUGINS_HELP = """Manage scanner plugins.

Built-in plugins: applications, homebrew, npm. Third-party plugins can
be registered via entry points in `frais.plugins`.

Examples:
  frais plugins
  frais plugins list
  frais plugins enable homebrew
  frais plugins disable npm
"""

IGNORE_HELP = """Manage apps to ignore during advise.

Ignored apps are excluded from version research. Useful for false positives
or apps you never want to update.

Storage:
  ~/.frais/config/ignore.txt (one app ID per line)

Examples:
  frais ignore
  frais ignore list
  frais ignore add com.anthropic.claude-code-url-handler
  frais ignore remove com.anthropic.claude-code-url-handler
"""

app = typer.Typer(help=APP_HELP, no_args_is_help=True, rich_markup_mode="rich", add_completion=False)
config_app = typer.Typer(help=CONFIG_HELP, rich_markup_mode="rich")
plugins_app = typer.Typer(help=PLUGINS_HELP, rich_markup_mode="rich")
ignore_app = typer.Typer(help=IGNORE_HELP, rich_markup_mode="rich")
app.add_typer(config_app, name="config")
app.add_typer(plugins_app, name="plugins")
app.add_typer(ignore_app, name="ignore")
console = Console()
logger = logging.getLogger(__name__)


def _configure_logging(verbose: bool, debug: bool, log_file: str | None, no_log: bool) -> None:
    file_level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    stderr_level = logging.DEBUG if debug else logging.INFO if verbose else logging.ERROR

    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(stderr_level)

    handlers: list[logging.Handler] = [stderr_handler]

    if not no_log:
        path = Path(log_file) if log_file else _DEFAULT_LOG_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > _LOG_MAX_SIZE:
                path.write_text("")
            file_handler = logging.FileHandler(str(path), encoding="utf-8")
            file_handler.setLevel(file_level)
            handlers.append(file_handler)
        except OSError as exc:
            print(f"Warning: could not open log file {path}: {exc}", flush=True)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.INFO if debug else logging.WARNING)


@app.callback()
def main(
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Print scan execution logs to stderr.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Print detailed debug logs, including subprocess command traces.",
        ),
    ] = False,
    log_file: Annotated[
        str | None,
        typer.Option(
            "--log-file",
            help="Override default log file path (~/.frais/log/frais.log).",
            metavar="PATH",
        ),
    ] = None,
    no_log: Annotated[
        bool,
        typer.Option(
            "--no-log",
            help="Disable file logging entirely.",
        ),
    ] = False,
) -> None:
    """Configure logging before running a command."""
    if platform.system() != "Darwin":
        console.print("[red]Frais only supports macOS.[/red]")
        raise typer.Exit(1)
    _configure_logging(verbose=verbose, debug=debug, log_file=log_file, no_log=no_log)
    if verbose or debug:
        log_target = "disabled" if no_log else (log_file or str(_DEFAULT_LOG_FILE))
        logger.info("logging enabled level=%s log_file=%s", "DEBUG" if debug else "INFO", log_target)


@app.command()
def doctor() -> None:
    """Show runtime readiness without changing the system.

    Prints detected OS version, CPU architecture, scanned Applications paths,
    plugin availability, and redacted BYOK status. Safe to run before
    configuring the tool.

    Example:
      frais doctor
    """
    from .plugins.registry import all_plugins
    from .system import detect_system

    system = detect_system()
    llm = load_config()
    logger.info("doctor system=%s %s arch=%s", system.os_name, system.os_version, system.arch)
    if llm:
        logger.info("doctor llm_ready=%s provider=%s", llm.is_ready, llm.provider.name)
    table = Table("Key", "Value")
    table.add_row("OS", f"{system.os_name} {system.os_version}")
    table.add_row("Arch", system.arch)
    table.add_row("Applications", ", ".join(system.applications_paths))
    for name, plugin in all_plugins().items():
        status = "available" if plugin.is_available() else "missing"
        default = "enabled" if plugin.enabled_by_default else "disabled"
        table.add_row(f"Plugin {name}", f"{status}, {default} by default")
    if llm:
        masked_key = "***" + llm.api_key[-4:] if len(llm.api_key) >= 4 else "***"
        table.add_row("LLM provider", llm.provider.name)
        table.add_row("LLM model", llm.model)
        table.add_row("LLM key", masked_key)
    else:
        table.add_row("LLM", "not configured (run `frais config manage`)")
    console.print(table)


@config_app.callback(invoke_without_command=True)
def config_default(ctx: typer.Context) -> None:
    """Show redacted BYOK config when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        config_show()


@config_app.command("manage")
def config_manage() -> None:
    """Interactively configure an LLM provider.

    Walk through provider selection, model choice, and API key entry.
    Writes the result to ~/.frais/config/config.toml.

    Example:
      frais config manage
    """
    from getpass import getpass

    from rich.prompt import IntPrompt

    from .llm import LLMClient
    from .config import ProviderConfig
    from .providers import PROVIDERS

    console.print()
    console.print("[bold]Select an LLM provider:[/bold]")
    console.print()
    for i, p in enumerate(PROVIDERS, 1):
        console.print(f"  {i}. {p.name}  [dim]({len(p.models)} models)[/dim]")
    console.print()

    idx = IntPrompt.ask(
        "Enter provider number",
        choices=[str(i) for i in range(1, len(PROVIDERS) + 1)],
        show_choices=False,
    )
    provider = PROVIDERS[idx - 1]
    console.print(f"  [green]{provider.name}[/green] selected.")
    console.print()

    console.print(f"[bold]Select a model for {provider.name}:[/bold]")
    console.print()
    for i, m in enumerate(provider.models, 1):
        default_mark = " [dim](thinking by default)[/dim]" if m.thinking_default else ""
        console.print(f"  {i}. {m.name}{default_mark}")
    console.print()

    model_idx = IntPrompt.ask(
        "Enter model number",
        choices=[str(i) for i in range(1, len(provider.models) + 1)],
        show_choices=False,
    )
    model = provider.models[model_idx - 1]
    console.print(f"  [green]{model.name}[/green] selected.")
    console.print()

    api_key = getpass(f"Enter API key for {provider.name} (input hidden): ").strip()
    if not api_key:
        console.print("[red]API key cannot be empty.[/red]")
        raise typer.Exit(1)
    console.print("  [green]API key received.[/green]")
    console.print()

    console.print(f"[bold]Testing connection to {provider.name}...[/bold]")
    try:
        test_config = ProviderConfig(
            provider=provider,
            model=model.id,
            api_key=api_key,
        )
        test_text = LLMClient(test_config).test_connection()
        console.print(f"  [green]Connection OK:[/green] {test_text.strip()}")
    except Exception as exc:
        console.print(f"  [yellow]Warning:[/yellow] test request failed: {exc}")
        if not typer.confirm("Save config anyway?", default=False):
            raise typer.Exit(1)

    save_config(provider.id, model.id, api_key)
    console.print()
    console.print(f"[green]Config saved to {CONFIG_PATH}[/green]")


@config_app.command("show")
def config_show() -> None:
    """Show current LLM provider config with secrets redacted.

    The API key is never printed; only presence and a final 4-character suffix
    are shown when available.

    Example:
      frais config show
    """
    llm = load_config()
    if not llm:
        console.print("[dim]Not configured. Run `frais config manage` to set up.[/dim]")
        return

    table = Table("Key", "Value")
    table.add_row("Provider", llm.provider.name)
    table.add_row("Model", llm.model)
    if llm.api_key:
        masked = "***" + llm.api_key[-4:] if len(llm.api_key) >= 4 else "***"
        table.add_row("API key", masked)
    else:
        table.add_row("API key", "missing")
    if llm.api_key_source:
        table.add_row("Key source", llm.api_key_source)
    console.print(table)


@config_app.command("path")
def config_path() -> None:
    """Print the default BYOK config file path.

    Example:
      frais config path
    """
    console.print(str(CONFIG_PATH))


@config_app.command("test")
def config_test() -> None:
    """Send a minimal LLM request to validate provider settings.

    This never prints the API key. It reports the provider, model,
    chat completions URL, and a short success or error message.

    Example:
      frais config test
    """
    from .llm import LLMClient, LLMRequestError

    try:
        config = require_config()
        console.print(f"Provider: {config.provider.name}")
        console.print(f"Model: {config.model}")
        console.print(f"Chat completions URL: {config.provider.chat_url}")
        text = LLMClient(config).test_connection()
    except (ValueError, LLMRequestError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"LLM test response: {text.strip()}")


@plugins_app.callback(invoke_without_command=True)
def plugins_default(ctx: typer.Context) -> None:
    """List plugins when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        plugins_list()


@plugins_app.command("list")
def plugins_list() -> None:
    """List all known plugins and their status.

    Shows all discovered plugins (built-in and third-party), whether the
    underlying tool is installed, default state, and effective enabled state.

    Example:
      frais plugins list
    """
    from .plugins.config import init_plugins_config, load_plugins_config
    from .plugins.registry import all_plugins

    init_plugins_config()
    persisted = load_plugins_config()
    table = Table("Plugin", "Available", "Default", "Effective")
    for name, plugin in all_plugins().items():
        available = "yes" if plugin.is_available() else "no"
        default = "enabled" if plugin.enabled_by_default else "disabled"
        effective = "enabled" if persisted.get(name, plugin.enabled_by_default) else "disabled"
        table.add_row(name, available, default, effective)
    console.print(table)


@plugins_app.command("enable")
def plugins_enable(
    name: Annotated[str, typer.Argument(help="Plugin name, for example: homebrew")],
) -> None:
    """Persistently enable a plugin.

    Example:
      frais plugins enable homebrew
    """
    from .plugins.config import init_plugins_config, save_plugin_state
    from .plugins.registry import all_plugins

    init_plugins_config()
    if name not in all_plugins():
        console.print(f"[red]Unknown plugin: {name}[/red]")
        raise typer.Exit(1)

    save_plugin_state(name, True)
    console.print(f"Plugin [bold]{name}[/bold] enabled (persisted).")


@plugins_app.command("disable")
def plugins_disable(
    name: Annotated[str, typer.Argument(help="Plugin name, for example: homebrew")],
) -> None:
    """Persistently disable a plugin.

    Example:
      frais plugins disable homebrew
    """
    from .plugins.config import init_plugins_config, save_plugin_state
    from .plugins.registry import all_plugins

    init_plugins_config()
    if name not in all_plugins():
        console.print(f"[red]Unknown plugin: {name}[/red]")
        raise typer.Exit(1)

    save_plugin_state(name, False)
    console.print(f"Plugin [bold]{name}[/bold] disabled (persisted).")


@ignore_app.callback(invoke_without_command=True)
def ignore_default(ctx: typer.Context) -> None:
    """List ignored apps when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        ignore_list()


@ignore_app.command("list")
def ignore_list() -> None:
    """List all ignored app IDs."""
    from .ignore import init_ignored
    init_ignored()
    ids = load_ignored()
    if not ids:
        console.print("No ignored apps.")
        return
    console.print(f"Ignored apps ({len(ids)}):")
    for app_id in sorted(ids):
        console.print(f"  {app_id}")


@ignore_app.command("add")
def ignore_add(
    app_id: Annotated[str, typer.Argument(help="App ID (bundle id) to ignore.")],
) -> None:
    """Add an app to the ignore list."""
    from .ignore import init_ignored
    init_ignored()
    if add_ignored(app_id):
        console.print(f"Added: {app_id}")
    else:
        console.print(f"Already ignored: {app_id}")


@ignore_app.command("remove")
def ignore_remove(
    app_id: Annotated[str, typer.Argument(help="App ID (bundle id) to remove from ignore list.")],
) -> None:
    """Remove an app from the ignore list."""
    from .ignore import init_ignored
    init_ignored()
    if remove_ignored(app_id):
        console.print(f"Removed: {app_id}")
    else:
        console.print(f"Not in ignore list: {app_id}")


# -- Action commands (delegated to commands/ modules) --

from .commands.advise import advise
from .commands.scan import scan
from .commands.summarize import summarize
from .commands.update import update

app.command(name="advise")(advise)
app.command(name="scan")(scan)
app.command(name="summarize")(summarize)
app.command(name="update")(update)


if __name__ == "__main__":
    app()
