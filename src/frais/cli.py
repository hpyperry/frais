from __future__ import annotations

import logging
import platform
from typing import Annotated

import typer
from rich.console import Console

from .commands.config import config_manage, config_path, config_show, config_test
from .commands.doctor import doctor
from .commands.ignore import ignore_add, ignore_list, ignore_remove
from .commands.plugins import plugins_disable, plugins_enable, plugins_list
from .logging_config import configure_logging
from .paths import ADVICE_CACHE, DEFAULT_LOG_FILE

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
console = Console()
logger = logging.getLogger(__name__)

# Backward-compatible names for tests and external imports.
_ADVICE_CACHE = ADVICE_CACHE
_DEFAULT_LOG_FILE = DEFAULT_LOG_FILE
_configure_logging = configure_logging


@app.callback()
def main(
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
    configure_logging(debug=debug, log_file=log_file, no_log=no_log)
    log_target = "disabled" if no_log else (log_file or str(DEFAULT_LOG_FILE))
    logger.info("logging enabled level=%s log_file=%s", "DEBUG" if debug else "INFO", log_target)


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


app.add_typer(config_app, name="config")
app.add_typer(plugins_app, name="plugins")
app.add_typer(ignore_app, name="ignore")

app.command()(doctor)
config_app.command("manage")(config_manage)
config_app.command("show")(config_show)
config_app.command("path")(config_path)
config_app.command("test")(config_test)
plugins_app.command("list")(plugins_list)
plugins_app.command("enable")(plugins_enable)
plugins_app.command("disable")(plugins_disable)
ignore_app.command("list")(ignore_list)
ignore_app.command("add")(ignore_add)
ignore_app.command("remove")(ignore_remove)

_heavy_commands_registered = False


def _register_heavy_commands() -> None:
    """Deferred registration of commands that pull in heavy dependencies.

    Avoids importing openai, anthropic, ddgs, and lxml during lightweight
    commands like ``frais config manage`` or ``frais doctor``.
    """
    global _heavy_commands_registered
    if _heavy_commands_registered:
        return
    from .commands.advise import advise
    from .commands.scan import scan
    from .commands.summarize import summarize
    from .commands.update import update

    app.command(name="advise")(advise)
    app.command(name="scan")(scan)
    app.command(name="summarize")(summarize)
    app.command(name="update")(update)
    _heavy_commands_registered = True


_HEAVY_COMMANDS = frozenset({"advise", "scan", "summarize", "update"})


def main_entry() -> None:
    """CLI entry point. Only registers heavy commands when needed."""
    import sys

    args = sys.argv[1:]
    if any(a in _HEAVY_COMMANDS for a in args):
        _register_heavy_commands()
    app()


if __name__ == "__main__":
    main_entry()
