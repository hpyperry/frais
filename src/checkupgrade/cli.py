from __future__ import annotations

import json
import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Annotated

import click
import signal
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.padding import Padding
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table

from .config import CONFIG_PATH, write_config_template
from .ignore import add_ignored, load_ignored, remove_ignored
from .models import PluginScanResult, SoftwareItem, SourceKind, ScanResult, UpdateCandidate

_DEFAULT_LOG_DIR = Path.home() / ".local" / "state" / "checkupgrade"
_DEFAULT_LOG_FILE = _DEFAULT_LOG_DIR / "checkupgrade.log"
_ADVICE_CACHE = _DEFAULT_LOG_DIR / "last_advice.json"
_LOG_MAX_SIZE = 5 * 1024 * 1024  # 5MB

APP_HELP = """CheckUpgrade scans macOS Applications and Homebrew for available updates.

Default scope:
  - Applications in /Applications and ~/Applications
  - Homebrew formulae and casks when `brew` is available

Safety model:
  - `doctor`, `config`, and `plugins` are read-only.
  - `advise` requires BYOK LLM configuration.
  - `update` only executes Homebrew commands after interactive confirmation.

Common examples:
  checkupgrade doctor
  checkupgrade config init
  checkupgrade advise
  checkupgrade advise --apps-only
  checkupgrade advise -j 5
  checkupgrade update --only node
  checkupgrade ignore add com.example.app
"""

CONFIG_HELP = """Manage BYOK LLM configuration.

BYOK means the user supplies their own OpenAI-compatible endpoint, model, and
API key. CheckUpgrade does not ship, create, or embed a service-side key.

Config file:
  ~/.config/checkupgrade/config.toml

Environment variables override the config file:
  CHECKUPGRADE_LLM_PROVIDER
  CHECKUPGRADE_LLM_API_KEY
  CHECKUPGRADE_LLM_BASE_URL
  CHECKUPGRADE_LLM_MODEL

Examples:
  checkupgrade config
  checkupgrade config show
  checkupgrade config init
  checkupgrade config path
  checkupgrade config test
"""

PLUGINS_HELP = """Manage package manager scanner plugins.

v1 includes the Homebrew plugin. It is enabled by default and scans both
formulae and casks. Other package managers are future plugin extension points.

Examples:
  checkupgrade plugins
  checkupgrade plugins list
"""

IGNORE_HELP = """Manage apps to ignore during advise.

Ignored apps are excluded from version research. Useful for false positives
or apps you never want to update.

Storage:
  ~/.config/checkupgrade/ignore.txt (one app ID per line)

Examples:
  checkupgrade ignore
  checkupgrade ignore list
  checkupgrade ignore add com.anthropic.claude-code-url-handler
  checkupgrade ignore remove com.anthropic.claude-code-url-handler
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
            help="Override default log file path (~/.local/state/checkupgrade/checkupgrade.log).",
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
    _configure_logging(verbose=verbose, debug=debug, log_file=log_file, no_log=no_log)
    if verbose or debug:
        log_target = "disabled" if no_log else (log_file or str(_DEFAULT_LOG_FILE))
        logger.info("logging enabled level=%s log_file=%s", "DEBUG" if debug else "INFO", log_target)


@app.command()
def doctor() -> None:
    """Show runtime readiness without changing the system.

    Prints detected OS version, CPU architecture, scanned Applications paths,
    Homebrew plugin availability, and redacted BYOK status. This command is
    safe to run before configuring the tool.

    Example:
      checkupgrade doctor
    """
    from .config import load_llm_config
    from .plugins.registry import all_plugins
    from .system import detect_system

    system = detect_system()
    llm = load_llm_config()
    logger.info("doctor system=%s %s arch=%s", system.os_name, system.os_version, system.arch)
    logger.info("doctor llm_ready=%s provider=%s", llm.is_ready, llm.provider)
    table = Table("Key", "Value")
    table.add_row("OS", f"{system.os_name} {system.os_version}")
    table.add_row("Arch", system.arch)
    table.add_row("Applications", ", ".join(system.applications_paths))
    for name, plugin in all_plugins().items():
        status = "available" if plugin.is_available() else "missing"
        default = "enabled" if plugin.enabled_by_default else "disabled"
        table.add_row(f"Plugin {name}", f"{status}, {default} by default")
    table.add_row("LLM provider", llm.provider)
    table.add_row("LLM base_url", llm.base_url or "missing")
    table.add_row("LLM model", llm.model or "missing")
    table.add_row("LLM key", f"configured (***{llm.api_key_suffix})" if llm.api_key_suffix else "missing")
    console.print(table)


@config_app.callback(invoke_without_command=True)
def config_default(ctx: typer.Context) -> None:
    """Show redacted BYOK config when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        config_show()


@config_app.command("init")
def config_init() -> None:
    """Create a local BYOK config template.

    The generated template is written to ~/.config/checkupgrade/config.toml.
    It contains placeholder provider/base_url/model fields and comments for the
    API key. It does not write a real key.

    Example:
      checkupgrade config init
    """
    path = write_config_template()
    logger.info("config template ready path=%s", path)
    console.print(f"Config template ready: {path}")


@config_app.command("show")
def config_show() -> None:
    """Show effective BYOK config with secrets redacted.

    Environment variables override ~/.config/checkupgrade/config.toml. The API
    key is never printed; only presence and a final 4-character suffix are
    shown when available.

    Example:
      checkupgrade config show
    """
    from .config import load_llm_config

    console.print_json(json.dumps(load_llm_config().safe_dict(), ensure_ascii=False))


@config_app.command("path")
def config_path() -> None:
    """Print the default BYOK config file path.

    Example:
      checkupgrade config path
    """
    console.print(str(CONFIG_PATH))


@config_app.command("test")
def config_test() -> None:
    """Send a minimal BYOK LLM request to validate provider settings.

    This never prints the API key. It reports the effective chat completions
    URL, model, and a short success or provider error message.

    Example:
      checkupgrade config test
    """
    from .agent import AgentClient, LLMRequestError, chat_completions_url
    from .config import require_raw_llm_config

    try:
        raw_config = require_raw_llm_config()
        console.print(f"Provider: {raw_config.provider}")
        console.print(f"Model: {raw_config.model}")
        console.print(f"Chat completions URL: {chat_completions_url(raw_config.base_url)}")
        text = AgentClient(raw_config).test_connection()
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
    underlying tool is installed, default state, any persisted override,
    and the effective enabled state.

    Example:
      checkupgrade plugins list
    """
    from .plugins.config import load_plugins_config
    from .plugins.registry import all_plugins

    persisted = load_plugins_config()
    table = Table("Plugin", "Available", "Default", "Persisted", "Effective")
    for name, plugin in all_plugins().items():
        available = "yes" if plugin.is_available() else "no"
        default = "enabled" if plugin.enabled_by_default else "disabled"
        if name in persisted:
            persisted_str = "enabled" if persisted[name] else "disabled"
        else:
            persisted_str = "-"
        if name in persisted:
            effective = "enabled" if persisted[name] else "disabled"
        else:
            effective = "enabled" if plugin.enabled_by_default else "disabled"
        table.add_row(name, available, default, persisted_str, effective)
    console.print(table)


@plugins_app.command("enable")
def plugins_enable(
    name: Annotated[str, typer.Argument(help="Plugin name, for example: homebrew")],
) -> None:
    """Persistently enable a plugin.

    Example:
      checkupgrade plugins enable homebrew
    """
    from .plugins.config import save_plugin_state
    from .plugins.registry import all_plugins

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
      checkupgrade plugins disable homebrew
    """
    from .plugins.config import save_plugin_state
    from .plugins.registry import all_plugins

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
    if add_ignored(app_id):
        console.print(f"Added: {app_id}")
    else:
        console.print(f"Already ignored: {app_id}")


@ignore_app.command("remove")
def ignore_remove(
    app_id: Annotated[str, typer.Argument(help="App ID (bundle id) to remove from ignore list.")],
) -> None:
    """Remove an app from the ignore list."""
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
            help="Comma-separated plugin names to advise on instead of Applications. v1 supports: homebrew.",
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
    """Scan and generate BYOK LLM update advice.

    Requires CHECKUPGRADE_LLM_API_KEY, CHECKUPGRADE_LLM_BASE_URL, and
    CHECKUPGRADE_LLM_MODEL, or equivalent values in the config file. The LLM is
    used for release research and summaries; missing or unreliable evidence is
    reported as unknown instead of being invented.

    Examples:
      checkupgrade advise
      checkupgrade advise --all
      checkupgrade advise --apps-only
      checkupgrade advise --json
      checkupgrade advise -j 5
    """
    from .agent import AgentClient
    from .config import require_raw_llm_config
    from .plugins.registry import all_plugins
    from .system import detect_system

    def _on_interrupt(signum, frame):
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        console.show_cursor()
        console.print()
        console.print("  [dim]Interrupted[/dim]")
        os._exit(0)

    orig_handler = signal.signal(signal.SIGINT, _on_interrupt)
    try:
        raw_config = require_raw_llm_config()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    logger.info("advise using provider=%s base_url=%s model=%s jobs=%d", raw_config.provider, raw_config.base_url, raw_config.model, jobs)
    agent = AgentClient(raw_config)

    system = detect_system()
    _explicit_plugins = _split_plugins(plugins)
    active = _select_plugins(apps_only, _explicit_plugins)

    # Print system banner before scanning
    console.print()
    plugin_labels = ", ".join(active)
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
        # Phase 1: Scan + Research per-plugin (research starts as soon as scan done)
        plugin_tasks: dict[str, int] = {}
        for name in active:
            plugin_tasks[name] = progress.add_task(name, total=1)
        result = ScanResult(system=system)
        ignored = load_ignored()

        researched_ids: set[str] = set()
        research_futures: dict = {}

        with ThreadPoolExecutor(max_workers=max(1, len(active))) as scan_pool, \
             ThreadPoolExecutor(max_workers=jobs) as research_pool:

            # Submit all scans
            scan_futures: dict = {}
            for name in active:
                plugin = all_plugins()[name]
                scan_fn = plugin.scan_all if show_all else plugin.scan
                scan_futures[scan_pool.submit(scan_fn, system)] = name

            # As each scan finishes, start its research (if needed) in the same loop
            for future in as_completed(scan_futures):
                name = scan_futures[future]
                plugin = all_plugins()[name]
                task_id = plugin_tasks[name]
                try:
                    pr = future.result()
                except Exception as exc:
                    logger.warning("scan failed for %s: %s", name, exc)
                    pr = PluginScanResult(skipped=[str(exc)])

                # Filter ignored
                if ignored:
                    pr.items = [it for it in pr.items if it.id not in ignored]
                    pr.candidates = [c for c in pr.candidates if c.item.id not in ignored]

                result.plugin_results[name] = pr

                if plugin.needs_research:
                    items_to_research = [it for it in pr.items
                                         if it.id not in {c.item.id for c in pr.candidates}]
                    if items_to_research:
                        progress.update(task_id, total=len(items_to_research), completed=0,
                                        description=f"{name}    researching")
                        for it in items_to_research:
                            r_fut = research_pool.submit(plugin.research, agent, it)
                            research_futures[r_fut] = (name, it)
                    else:
                        progress.update(task_id, completed=1,
                                        description=f"{name}    {len(pr.items)} items, {len(pr.candidates)} updates")
                else:
                    desc = f"{name}    {len(pr.items)} items"
                    if pr.candidates:
                        desc += f", {len(pr.candidates)} updates"
                    progress.update(task_id, completed=1, description=desc)

            # Collect research results as they complete
            for r_future in as_completed(research_futures):
                name, item = research_futures[r_future]
                pr = result.plugin_results[name]
                task_id = plugin_tasks[name]
                researched_ids.add(item.id)
                try:
                    candidate = r_future.result()
                except Exception as exc:
                    logger.warning("research failed for %s: %s", item.name, exc)
                    progress.advance(task_id)
                    continue
                if candidate:
                    pr.candidates.append(candidate)
                progress.advance(task_id)

        # Finalize research plugin task descriptions
        for name in active:
            pr = result.plugin_results[name]
            plugin = all_plugins()[name]
            desc = f"{name}    {len(pr.items)} items"
            if pr.candidates:
                desc += f", {len(pr.candidates)} updates"
            if plugin.needs_research:
                progress.update(plugin_tasks[name], total=1, completed=1, description=desc)




        # Phase 3: Summaries
        all_candidates = result.all_candidates
        if all_candidates:
            summarize_task = progress.add_task("Summaries", total=len(all_candidates))
            _summarize_concurrent(agent, all_candidates, jobs, progress, summarize_task)

    if json_output:
        console.print_json(json.dumps(result.to_dict(), ensure_ascii=False))
        return

    # Save advice cache for update command (atomic write via temp file)
    try:
        _DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = _ADVICE_CACHE.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        tmp_path.replace(_ADVICE_CACHE)
        logger.info("advice cache saved to %s", _ADVICE_CACHE)
    except OSError as exc:
        logger.warning("failed to save advice cache: %s", exc)

    _print_advise_result(result, researched_ids, len(ignored), show_all=show_all)

    signal.signal(signal.SIGINT, orig_handler)


def _select_plugins(apps_only: bool, explicit: list[str] | None) -> list[str]:
    from .plugins.config import load_plugins_config
    from .plugins.registry import all_plugins

    if apps_only:
        return ["applications"]
    if explicit:
        return [name for name in explicit if name in all_plugins()]

    persisted = load_plugins_config()
    result: list[str] = []
    for name, plugin in all_plugins().items():
        if name in persisted:
            if persisted[name]:
                result.append(name)
        elif plugin.enabled_by_default:
            result.append(name)
    return result


def _summarize_one(agent: AgentClient, candidate: UpdateCandidate) -> None:
    try:
        candidate.ai_summary = agent.summarize_candidate(candidate)
    except Exception as exc:
        logger.warning("summary failed for %s: %s", candidate.item.name, exc)


def _summarize_concurrent(
    agent: AgentClient, candidates: list[UpdateCandidate], jobs: int,
    progress: Progress | None = None, task_id: object | None = None,
) -> None:
    if not candidates:
        return
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(_summarize_one, agent, c) for c in candidates]
        for future in as_completed(futures):
            future.result()
            if progress is not None and task_id is not None:
                progress.advance(task_id)


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

    Loads results from the last `checkupgrade advise` run. Shows each candidate
    with AI advice for confirmation. Auto-updatable packages (Homebrew) execute
    directly; others show the recommended action.

    Run `checkupgrade advise` first to generate the update candidates.

    Examples:
      checkupgrade update
      checkupgrade update fr.handbrake.HandBrake
    """
    if not _ADVICE_CACHE.exists():
        console.print("No advice cache found. Run [bold]checkupgrade advise[/bold] first.")
        raise typer.Exit(1)

    try:
        data = json.loads(_ADVICE_CACHE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"Failed to read advice cache: {exc}")
        raise typer.Exit(1)

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

    for candidate in candidates:
        # Ensure App Store apps have an open command
        if candidate.item.source == SourceKind.APP_STORE and not candidate.command:
            candidate.command, candidate.can_auto_update = _resolve_app_store_command(candidate.item)

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

        if candidate.can_auto_update:
            logger.info("update executing command=%s", " ".join(candidate.command))
            subprocess.run(candidate.command, check=False)
        else:
            if candidate.item.path and typer.confirm("    Open app for update?", default=False):
                subprocess.run(["open", candidate.item.path], check=False)
            else:
                console.print("    Skipped.")
def _resolve_app_store_command(item: SoftwareItem) -> tuple[list[str], bool]:
    """Try to get App Store trackId and return (command, can_auto_update)."""
    try:
        import httpx
        response = httpx.get(
            "https://itunes.apple.com/lookup",
            params={"bundleId": item.id, "country": "cn"},
            timeout=httpx.Timeout(5.0, read=10.0),
        )
        response.raise_for_status()
        data = response.json()
        if data.get("resultCount", 0) > 0:
            track_id = data["results"][0].get("trackId")
            if track_id:
                return ["open", f"macappstore://apps.apple.com/app/id{track_id}"], True
    except Exception as exc:
        logger.debug("itunes lookup failed for %s: %s", item.name, exc)
    return [], False




def _split_plugins(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _print_advise_result(result: ScanResult, researched_ids: set[str], ignored_count: int = 0,
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
                    if item.id in researched_ids:
                        console.print(f"  {item.id}")
                        console.print(f"    {item.name} | {source} | {current}  [dim]up to date[/dim]")
                    elif item.source in (SourceKind.HOMEBREW_FORMULA, SourceKind.HOMEBREW_CASK,
                                         SourceKind.NPM_GLOBAL):
                        console.print(f"  {item.id}")
                        console.print(f"    {item.name} | {current}  [dim]up to date[/dim]")
                    else:
                        console.print(f"  {item.id}")
                        console.print(f"    {item.name} | {source} | {current}  [red]failed[/red]")
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
        console.print(f"  [dim]{ignored_count} app(s) ignored (use `checkupgrade ignore list` to review)[/dim]")




if __name__ == "__main__":
    app()
