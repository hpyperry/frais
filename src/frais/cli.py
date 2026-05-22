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
from rich.markdown import Markdown
from rich.padding import Padding
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table

from .config import CONFIG_PATH, load_config, require_config, save_config
from .ignore import add_ignored, load_ignored, remove_ignored
from .models import PluginScanResult, SourceKind, ScanResult, UpdateCandidate


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
  frais advise --apps-only
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
    # Stderr: show only errors by default; INFO with --verbose; DEBUG with --debug
    stderr_level = logging.DEBUG if debug else logging.INFO if verbose else logging.ERROR

    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(stderr_level)

    handlers: list[logging.Handler] = [stderr_handler]

    if not no_log:
        path = Path(log_file) if log_file else _DEFAULT_LOG_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Auto-truncate if file exceeds max size
            if path.exists() and path.stat().st_size > _LOG_MAX_SIZE:
                path.write_text("")
            file_handler = logging.FileHandler(str(path), encoding="utf-8")
            file_handler.setLevel(file_level)
            handlers.append(file_handler)
        except OSError as exc:
            # Fall back to stderr-only if file logging fails
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

    # Step 1: Select provider
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

    # Step 2: Select model
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

    # Step 3: API key
    api_key = getpass(f"Enter API key for {provider.name} (input hidden): ").strip()
    if not api_key:
        console.print("[red]API key cannot be empty.[/red]")
        raise typer.Exit(1)
    console.print("  [green]API key received.[/green]")
    console.print()

    # Step 4: Test connection
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

    # Step 5: Save
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


@app.command()
def advise(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print scan results and advice as machine-readable JSON."),
    ] = False,
    apps_only: Annotated[
        bool,
        typer.Option("--apps-only", help="Only advise on Applications; skip package manager plugins."),
    ] = False,
    plugins: Annotated[
        str | None,
        typer.Option(
            "--plugins",
            help="Comma-separated plugin names to advise on (e.g. homebrew,npm).",
            metavar="NAMES",
        ),
    ] = None,
    jobs: Annotated[
        int,
        typer.Option(
            "--jobs",
            "-j",
            help="Number of concurrent LLM requests.",
            min=1,
            max=20,
        ),
    ] = 10,
    show_all: Annotated[
        bool,
        typer.Option("--all", help="Show all installed software, including up-to-date items."),
    ] = False,
) -> None:
    """Scan and generate LLM-powered update advice.

    Requires a configured LLM provider (run `frais config manage` first).
    The LLM is used for release research and summaries; missing or
    unreliable evidence is reported as unknown instead of being invented.

    Examples:
      frais advise
      frais advise --all
      frais advise --apps-only
      frais advise --json
      frais advise -j 5
    """
    from .llm import LLMClient
    from .plugins.registry import all_plugins
    from .system import detect_system

    try:
        config = require_config()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    logger.info("advise using provider=%s model=%s jobs=%d", config.provider.name, config.model, jobs)
    llm = LLMClient(config)

    def _on_interrupt(signum, frame):
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        os.write(1, b"\033[?25h\n")
        os._exit(130)

    orig_handler = signal.signal(signal.SIGINT, _on_interrupt)
    try:
        from .coordinator import run_summaries, select_plugins as _coord_select
        from .plugins.registry import all_plugins

        system = detect_system()
        _explicit_plugins = _split_plugins(plugins)
        active_plugins = _coord_select(apps_only, _explicit_plugins)

        # Print system banner
        console.print()
        plugin_labels = ", ".join(active_plugins)
        console.print(
            f"  [bold cyan]OS:[/] {system.os_name} {system.os_version}  "
            f"[bold cyan]Arch:[/] {system.arch}  "
            f"[bold cyan]Plugins:[/] {plugin_labels}"
        )
        console.print()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            # Per-plugin scan tasks — step names from plugin.scan_steps
            plugin_tasks: dict[str, int] = {}
            plugin_steps: dict[str, int] = {}  # current step index per plugin
            plugin_active: dict[str, ScannerPlugin] = {}

            for name in active_plugins:
                p = all_plugins()[name]
                plugin_active[name] = p
                plugin_steps[name] = 0
                label = p.scan_steps[0] if p.scan_steps else name
                plugin_tasks[name] = progress.add_task(label, total=1)

            def _on_plugin_progress(pname: str, step: int, done: int) -> None:
                task_id = plugin_tasks.get(pname)
                if task_id is None:
                    return
                plugin = plugin_active.get(pname)
                if plugin and step != plugin_steps.get(pname):
                    plugin_steps[pname] = step
                    label = (plugin.scan_steps[step]
                              if step < len(plugin.scan_steps)
                              else pname)
                    progress.update(task_id, description=label, total=1, completed=0)
                progress.update(task_id, completed=done)

            # Phase 1: concurrent scans — plugins own their steps
            from .coordinator import run_scan
            result = run_scan(plugin_active, system, show_all=show_all,
                              jobs=jobs, on_plugin_progress=_on_plugin_progress)

            # Apply ignore list
            ignored = load_ignored()
            if ignored:
                for pr in result.plugin_results.values():
                    pr.items = [it for it in pr.items if it.id not in ignored]
                    pr.candidates = [c for c in pr.candidates if c.item.id not in ignored]

            # Finalize scan task descriptions
            for name in active_plugins:
                pr = result.plugin_results.get(name)
                if pr is None:
                    continue
                desc = f"{name}    {len(pr.items)} items"
                if pr.candidates:
                    desc += f", {len(pr.candidates)} updates"
                progress.update(plugin_tasks[name], total=1, completed=1, description=desc)

            # Phase 2: Summaries
            all_candidates = result.all_candidates
            if all_candidates:
                summarize_task = progress.add_task("Summaries", total=len(all_candidates))
                candidate_plugin_map: dict[int, str] = {}
                for pname, pr in result.plugin_results.items():
                    for c in pr.candidates:
                        candidate_plugin_map[id(c)] = pname
                run_summaries(llm, all_candidates, candidate_plugin_map,
                              plugin_active, max_workers=jobs,
                              on_progress=lambda: progress.advance(summarize_task))

        if json_output:
            console.print_json(json.dumps(result.to_dict(), ensure_ascii=False))
            return

        # Save advice cache
        try:
            _DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
            tmp_path = _ADVICE_CACHE.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            tmp_path.replace(_ADVICE_CACHE)
            logger.info("advice cache saved to %s", _ADVICE_CACHE)
        except OSError as exc:
            logger.warning("failed to save advice cache: %s", exc)

        _print_advise_result(result, len(ignored), show_all=show_all)

    finally:
        signal.signal(signal.SIGINT, orig_handler)


@app.command()
def scan(
    plugins: Annotated[
        str | None,
        typer.Option(
            "--plugins",
            help="Comma-separated plugin names to scan (e.g. homebrew,npm).",
            metavar="NAMES",
        ),
    ] = None,
    show_all: Annotated[
        bool,
        typer.Option("--all", help="Show all installed software, including up-to-date items."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Scan installed software for available updates.

    Runs every enabled plugin's scan step and reports discovered items
    and update candidates. With --json, prints machine-readable JSON
    suitable for consumption by external agents.

    Examples:
      frais scan
      frais scan --plugins applications --json
      frais scan --all
    """
    from .coordinator import select_plugins as _coord_select
    from .plugins.registry import all_plugins
    from .system import detect_system

    system = detect_system()
    _explicit = _split_plugins(plugins)
    active = _coord_select(apps_only=False, explicit=_explicit)

    # Simple text-based progress for agent mode
    if not json_output:
        console.print()
        console.print(f"Scanning with: {', '.join(active)}")

    def _on_progress(pname: str, step: int, done: int) -> None:
        if not json_output:
            p = active.get(pname)
            label = (p.scan_steps[step] if p and step < len(p.scan_steps) else pname)
            console.print(f"  {pname}: {label} ({done})")

    from .coordinator import run_scan as _run_scan
    result = _run_scan(active, system, show_all=show_all,
                       jobs=10, on_plugin_progress=_on_progress)

    # Apply ignore list
    from .ignore import load_ignored
    ignored = load_ignored()
    if ignored:
        for pr in result.plugin_results.values():
            pr.items = [it for it in pr.items if it.id not in ignored]
            pr.candidates = [c for c in pr.candidates if c.item.id not in ignored]

    if json_output:
        console.print_json(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        _print_advise_result(result, len(ignored), show_all=show_all)


@app.command()
def summarize(
    item_id: Annotated[
        str,
        typer.Argument(help="Item ID from a previous scan (e.g. com.example.app)."),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON."),
    ] = False,
) -> None:
    """Generate an AI summary for a single candidate.

    Loads the cached result from the last `frais advise` or `frais scan` run,
    finds the candidate matching *item_id*, and calls its plugin's summarize().

    Examples:
      frais summarize com.google.Chrome
      frais summarize brew:node --json
    """
    if not _ADVICE_CACHE.exists():
        console.print("No scan cache found. Run [bold]frais advise[/bold] or [bold]frais scan[/bold] first.")
        raise typer.Exit(1)

    try:
        data = json.loads(_ADVICE_CACHE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"Failed to read scan cache: {exc}")
        raise typer.Exit(1)

    from .llm import LLMClient
    from .plugins.registry import all_plugins

    # Find candidate and its plugin
    candidate: UpdateCandidate | None = None
    plugin_name: str | None = None
    if "plugin_results" in data:
        for pname, pr in data["plugin_results"].items():
            for raw in pr.get("candidates", []):
                if raw.get("item", {}).get("id") == item_id:
                    try:
                        candidate = UpdateCandidate.from_dict(raw)
                    except Exception:
                        continue
                    plugin_name = pname
                    break
            if candidate:
                break

    if candidate is None:
        console.print(f"[red]No candidate found for: {item_id}[/red]")
        raise typer.Exit(1)

    try:
        config = require_config()
        llm = LLMClient(config)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    plugin = all_plugins().get(plugin_name or "")
    if plugin is None:
        console.print(f"[red]Plugin not found: {plugin_name}[/red]")
        raise typer.Exit(1)

    summary = plugin.summarize(llm, candidate)
    if json_output:
        console.print_json(json.dumps({"item_id": item_id, "ai_summary": summary}, ensure_ascii=False))
    else:
        console.print(summary or "(no summary generated)")


@app.command()
def update(
    only: Annotated[
        str | None,
        typer.Argument(
            help="Filter by exact id or software name. Omit to review all candidates.",
            metavar="ID_OR_NAME",
        ),
    ] = None,
) -> None:
    """Interactively review and execute updates with AI advice.

    Loads results from the last `frais advise` run. Shows each candidate
    with AI advice for confirmation. Auto-updatable packages (Homebrew, npm)
    execute directly; others show the recommended action.

    Run `frais advise` first to generate the update candidates.

    Examples:
      frais update
      frais update npm
    """
    if not _ADVICE_CACHE.exists():
        console.print("No advice cache found. Run [bold]frais advise[/bold] first.")
        raise typer.Exit(1)

    try:
        data = json.loads(_ADVICE_CACHE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"Failed to read advice cache: {exc}")
        raise typer.Exit(1)

    from .plugins.registry import all_plugins

    # Build candidate → plugin mapping from cache
    plugin_map: dict[str, str] = {}  # candidate item id → plugin name
    if "plugin_results" in data:
        for plugin_name, pr in data["plugin_results"].items():
            for raw_cand in pr.get("candidates", []):
                item_data = raw_cand.get("item", {})
                plugin_map[item_data.get("id", "")] = plugin_name

    # Parse candidates from cached data (v2 format: plugin_results)
    raw_candidates: list[dict] = []
    if "plugin_results" in data:
        for pr in data["plugin_results"].values():
            raw_candidates.extend(pr.get("candidates", []))
    else:
        raw_candidates = data.get("candidates", [])
    candidates: list[UpdateCandidate] = []
    for raw in raw_candidates:
        try:
            candidates.append(UpdateCandidate.from_dict(raw))
        except Exception as exc:
            logger.warning("failed to parse cached candidate: %s", exc)

    if only:
        candidates = [c for c in candidates if c.item.id == only or c.item.name == only]
    if not candidates:
        console.print("No update candidates found.")
        return

    plugins = all_plugins()

    for candidate in candidates:
        console.print()
        console.print(f"  {candidate.item.id}")
        console.print(f"    {candidate.item.name} | {candidate.item.source.value}")
        console.print(
            f"    {candidate.item.current_version or 'unknown'} → "
            f"[green]{candidate.latest_version or 'unknown'}[/green]"
        )
        if candidate.ai_summary:
            console.print(Padding(Markdown(candidate.ai_summary), (0, 0, 0, 4)))
        if candidate.can_auto_update and candidate.item.source != SourceKind.APP_STORE:
            console.print(f"    Command: {' '.join(candidate.command)}")
        elif not candidate.can_auto_update:
            console.print(f"    [dim]Manual update required[/dim]")

        if not typer.confirm("Proceed?", default=False):
            logger.info("update skipped name=%s", candidate.item.name)
            continue

        plugin_name = plugin_map.get(candidate.item.id)
        plugin = plugins.get(plugin_name) if plugin_name else None
        if plugin and plugin.update(candidate):
            logger.info("update executed plugin=%s name=%s", plugin_name, candidate.item.name)
        elif not candidate.can_auto_update and candidate.item.path:
            if typer.confirm("    Open app for update?", default=False):
                subprocess.run(["open", candidate.item.path], check=False)
            else:
                console.print("    Skipped.")
        else:
            console.print("    [dim]Update not available.[/dim]")




def _split_plugins(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _print_advise_result(result: ScanResult, ignored_count: int = 0,
                         show_all: bool = False) -> None:
    from .plugins.registry import all_plugins

    candidate_item_ids = {c.item.id for c in result.all_candidates}
    plugins = all_plugins()

    for name, pr in result.plugin_results.items():
        plugin = plugins.get(name)
        color = plugin.display_color if plugin else "white"
        if show_all:
            current_items = [it for it in pr.items if it.id not in candidate_item_ids]
            if current_items:
                console.print(Rule(f"[bold]{name}[/] — {len(current_items)} up to date", style=color))
                for item in sorted(current_items, key=lambda x: x.name.lower()):
                    current = item.current_version or "unknown"
                    source = item.source.value
                    console.print(f"  {item.id}")
                    console.print(f"    {item.name} | {source} | {current}  [dim]up to date[/dim]")
                console.print()
        for skipped in pr.skipped:
            console.print(f"  [dim]Skipped ({name}): {skipped}[/dim]")

    if result.all_candidates:
        console.print(Rule(f"[bold]Updates available[/] ({len(result.all_candidates)})", style="green"))
        console.print()
        for candidate in result.all_candidates:
            console.print(f"  {candidate.item.id}")
            console.print(f"    {candidate.item.name} | {candidate.item.source.value}")
            console.print(
                f"    {candidate.item.current_version or 'unknown'} → "
                f"[green]{candidate.latest_version or 'unknown'}[/green]  [{candidate.recommended_action}]"
            )
            console.print()

    if ignored_count:
        console.print(f"  [dim]{ignored_count} app(s) ignored (use `frais ignore list` to review)[/dim]")




if __name__ == "__main__":
    app()
