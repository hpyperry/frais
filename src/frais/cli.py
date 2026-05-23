from __future__ import annotations

import json
import logging
import os
import platform
import signal
import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .commands._output import exit_with_error, print_json_success
from .commands.config import config_manage, config_path, config_show, config_test
from .commands.ignore import ignore_list, ignore_add, ignore_remove
from .store.config_store import CONFIG_PATH, load_config
from .store.ignore_store import add_ignored, load_ignored, remove_ignored
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
    # Always suppress HTTP-level loggers — they may emit Authorization headers at DEBUG
    for logger_name in ("httpcore", "urllib3", "ddgs", "primp"):
        logging.getLogger(logger_name).setLevel(logging.INFO)


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
def doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
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
    llm_cfg = load_config()
    logger.info("doctor system=%s %s arch=%s", system.os_name, system.os_version, system.arch)
    if llm_cfg:
        logger.info("doctor llm_ready=%s provider=%s", llm_cfg.is_ready, llm_cfg.provider.name)

    if json_output:
        plugins_data: dict[str, dict[str, str]] = {}
        for name, plugin in all_plugins().items():
            plugins_data[name] = {
                "available": "yes" if plugin.is_available() else "no",
                "default": "enabled" if plugin.enabled_by_default else "disabled",
            }
        llm_data: dict[str, str | bool] | None = None
        if llm_cfg:
            masked_key = "***" + llm_cfg.api_key[-4:] if len(llm_cfg.api_key) >= 4 else "***"
            llm_data = {
                "configured": llm_cfg.is_ready,
                "provider": llm_cfg.provider.name,
                "model": llm_cfg.model,
                "key_suffix": masked_key,
            }
        print_json_success(system=system.to_dict(), plugins=plugins_data, llm=llm_data)
        return

    table = Table("Key", "Value")
    table.add_row("OS", f"{system.os_name} {system.os_version}")
    table.add_row("Arch", system.arch)
    table.add_row("Applications", ", ".join(system.applications_paths))
    for name, plugin in all_plugins().items():
        status = "available" if plugin.is_available() else "missing"
        default = "enabled" if plugin.enabled_by_default else "disabled"
        table.add_row(f"Plugin {name}", f"{status}, {default} by default")
    if llm_cfg:
        masked_key = "***" + llm_cfg.api_key[-4:] if len(llm_cfg.api_key) >= 4 else "***"
        table.add_row("LLM provider", llm_cfg.provider.name)
        table.add_row("LLM model", llm_cfg.model)
        table.add_row("LLM key", masked_key)
    else:
        table.add_row("LLM", "not configured (run `frais config manage`)")
    console.print(table)


@config_app.callback(invoke_without_command=True)
def config_default(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Show redacted BYOK config when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        config_show(json_output=json_output)


config_app.command("manage")(config_manage)
config_app.command("show")(config_show)
config_app.command("path")(config_path)
config_app.command("test")(config_test)


@plugins_app.callback(invoke_without_command=True)
def plugins_default(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """List plugins when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        plugins_list(json_output=json_output)


@plugins_app.command("list")
def plugins_list(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """List all known plugins and their status.

    Shows all discovered plugins (built-in and third-party), whether the
    underlying tool is installed, default state, and effective enabled state.

    Example:
      frais plugins list
    """
    from .store.plugin_store import init_plugins_config, load_plugins_config
    from .plugins.registry import all_plugins

    init_plugins_config()
    persisted = load_plugins_config()

    if json_output:
        plugins_data: list[dict[str, str]] = []
        for name, plugin in all_plugins().items():
            plugins_data.append({
                "name": name,
                "available": "yes" if plugin.is_available() else "no",
                "default": "enabled" if plugin.enabled_by_default else "disabled",
                "effective": "enabled" if persisted.get(name, plugin.enabled_by_default) else "disabled",
            })
        print_json_success(plugins=plugins_data)
        return

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
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Persistently enable a plugin.

    Example:
      frais plugins enable homebrew
    """
    from .store.plugin_store import init_plugins_config, save_plugin_state
    from .plugins.registry import all_plugins

    init_plugins_config()
    if name not in all_plugins():
        exit_with_error(
        f"Unknown plugin: {name}", json_output,
        reason="unknown_plugin",
        hint="Run `frais plugins list --json` to see available plugins.",
        plugin_name=name)

    save_plugin_state(name, True)
    if json_output:
        print_json_success(plugin=name, action="enabled")
        return
    console.print(f"Plugin [bold]{name}[/bold] enabled (persisted).")


@plugins_app.command("disable")
def plugins_disable(
    name: Annotated[str, typer.Argument(help="Plugin name, for example: homebrew")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Persistently disable a plugin.

    Example:
      frais plugins disable homebrew
    """
    from .store.plugin_store import init_plugins_config, save_plugin_state
    from .plugins.registry import all_plugins

    init_plugins_config()
    if name not in all_plugins():
        exit_with_error(
        f"Unknown plugin: {name}", json_output,
        reason="unknown_plugin",
        hint="Run `frais plugins list --json` to see available plugins.",
        plugin_name=name)

    save_plugin_state(name, False)
    if json_output:
        print_json_success(plugin=name, action="disabled")
        return
    console.print(f"Plugin [bold]{name}[/bold] disabled (persisted).")



@ignore_app.callback(invoke_without_command=True)
def ignore_default(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """List ignored apps when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        ignore_list(json_output=json_output)

ignore_app.command("list")(ignore_list)
ignore_app.command("add")(ignore_add)
ignore_app.command("remove")(ignore_remove)



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
