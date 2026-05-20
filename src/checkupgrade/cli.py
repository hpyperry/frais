from __future__ import annotations

import json
import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Annotated

import click
import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .agent import AgentClient, LLMRequestError, chat_completions_url
from .config import CONFIG_PATH, load_llm_config, require_raw_llm_config, write_config_template
from .models import SoftwareItem, ScanResult, UpdateCandidate
from .plugins.registry import all_plugins, enabled_plugins
from .research import research_application_update
from .scanners.applications import scan_applications
from .system import detect_system

_DEFAULT_LOG_DIR = Path.home() / ".local" / "state" / "checkupgrade"
_DEFAULT_LOG_FILE = _DEFAULT_LOG_DIR / "checkupgrade.log"
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

app = typer.Typer(help=APP_HELP, no_args_is_help=True, rich_markup_mode="rich")
config_app = typer.Typer(help=CONFIG_HELP, rich_markup_mode="rich")
plugins_app = typer.Typer(help=PLUGINS_HELP, rich_markup_mode="rich")
app.add_typer(config_app, name="config")
app.add_typer(plugins_app, name="plugins")
console = Console()
logger = logging.getLogger(__name__)


def _configure_logging(verbose: bool, debug: bool, log_file: str | None, no_log: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if not no_log:
        path = Path(log_file) if log_file else _DEFAULT_LOG_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Auto-truncate if file exceeds max size
            if path.exists() and path.stat().st_size > _LOG_MAX_SIZE:
                path.write_text("")
            handlers.append(logging.FileHandler(str(path), encoding="utf-8"))
        except OSError as exc:
            # Fall back to stderr-only if file logging fails
            print(f"Warning: could not open log file {path}: {exc}", flush=True)

    logging.basicConfig(
        level=level,
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
    """List known package manager plugins and availability.

    v1 ships with the Homebrew plugin enabled by default. If Homebrew is not on
    PATH, scans continue with Applications and report the plugin as skipped.

    Example:
      checkupgrade plugins list
    """
    table = Table("Plugin", "Available", "Default")
    for name, plugin in all_plugins().items():
        table.add_row(name, str(plugin.is_available()), str(plugin.enabled_by_default))
    console.print(table)


@plugins_app.command("enable")
def plugins_enable(
    name: Annotated[str, typer.Argument(help="Plugin name, for example: homebrew")],
) -> None:
    """Explain how to enable a plugin for one run.

    Persistent plugin configuration is intentionally not implemented in v1.
    """
    console.print(f"Plugin persistence is not implemented in v1. Use `--plugins {name}` for one run.")


@plugins_app.command("disable")
def plugins_disable(
    name: Annotated[str, typer.Argument(help="Plugin name, for example: homebrew")],
) -> None:
    """Explain how to disable a plugin for one run.

    Persistent plugin configuration is intentionally not implemented in v1.
    Use `--apps-only` to skip plugins, or `--plugins` to choose a subset.
    """
    console.print(f"Plugin persistence is not implemented in v1. Use `--apps-only` or `--plugins` for one run.")


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
) -> None:
    """Scan and generate BYOK LLM update advice.

    Requires CHECKUPGRADE_LLM_API_KEY, CHECKUPGRADE_LLM_BASE_URL, and
    CHECKUPGRADE_LLM_MODEL, or equivalent values in the config file. The LLM is
    used for release research and summaries; missing or unreliable evidence is
    reported as unknown instead of being invented.

    Examples:
      checkupgrade advise
      checkupgrade advise --apps-only
      checkupgrade advise --json
      checkupgrade advise -j 5
    """
    try:
        raw_config = require_raw_llm_config()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    logger.info("advise using provider=%s base_url=%s model=%s jobs=%d", raw_config.provider, raw_config.base_url, raw_config.model, jobs)
    agent = AgentClient(raw_config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        # Phase 1: Scan
        scan_task = progress.add_task("Scanning", total=2)
        result = run_scan(apps_only=apps_only, plugin_names=_split_plugins(plugins))
        progress.update(scan_task, completed=2, description=f"Scanning ({len(result.applications)} apps, {len(result.candidates)} plugin updates)")

        # Phase 2: Research applications
        app_count = len(result.applications)
        if app_count:
            research_task = progress.add_task("Researching apps", total=app_count)
            researched, researched_ids = _research_apps_concurrent(agent, result.applications, jobs, progress, research_task)
            result.candidates.extend(researched)
        else:
            researched_ids = set()

        # Phase 3: Summarize candidates
        cand_count = len(result.candidates)
        if cand_count:
            summarize_task = progress.add_task("Generating summaries", total=cand_count)
            _summarize_concurrent(agent, result.candidates, jobs, progress, summarize_task)

    if json_output:
        console.print_json(json.dumps(result.to_dict(), ensure_ascii=False))
        return
    _print_advise_result(result, researched_ids)


def _research_one(agent: AgentClient, item: SoftwareItem) -> UpdateCandidate | None:
    logger.info("research application name=%s id=%s source=%s version=%s", item.name, item.id, item.source.value, item.current_version)
    try:
        candidate = research_application_update(agent, item)
    except Exception as exc:
        logger.warning("research failed for %s: %s", item.name, exc)
        return None
    if candidate:
        logger.info("application update candidate name=%s latest=%s action=%s", item.name, candidate.latest_version, candidate.recommended_action)
    else:
        logger.info("application no newer reliable version found name=%s id=%s", item.name, item.id)
    return candidate


def _research_apps_concurrent(
    agent: AgentClient, applications: list[SoftwareItem], jobs: int,
    progress: Progress | None = None, task_id: object | None = None,
) -> tuple[list[UpdateCandidate], set[str]]:
    if not applications:
        return [], set()
    results: list[UpdateCandidate] = []
    researched_ids: set[str] = set()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(_research_one, agent, item): item for item in applications}
        for future in as_completed(futures):
            item = futures[future]
            researched_ids.add(item.id)
            try:
                candidate = future.result()
            except Exception as exc:
                logger.warning("research failed for %s: %s", item.name, exc)
                continue
            if candidate:
                results.append(candidate)
            if progress and task_id:
                progress.advance(task_id)
    return results, researched_ids


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
            future.result()  # raise if any unexpected error
            if progress and task_id:
                progress.advance(task_id)


@app.command()
def update(
    only: Annotated[
        str | None,
        typer.Option(
            "--only",
            help="Update one auto-updatable candidate by exact candidate id or software name.",
            metavar="ID_OR_NAME",
        ),
    ] = None,
    plugins: Annotated[
        str | None,
        typer.Option(
            "--plugins",
            help="Comma-separated plugin names to update from. v1 auto-update support is Homebrew only.",
            metavar="NAMES",
        ),
    ] = None,
) -> None:
    """Interactively execute confirmed auto-update commands.

    v1 only auto-executes Homebrew formula/cask updates. Applications discovered
    from local builds, downloads, or unknown sources are reported by advise but
    are not overwritten automatically. Every command is shown before it is run
    and requires confirmation.

    Examples:
      checkupgrade update
      checkupgrade update --only node
      checkupgrade update --plugins homebrew --only docker
    """
    result = run_scan(apps_only=False, plugin_names=_split_plugins(plugins))
    candidates = [candidate for candidate in result.candidates if candidate.can_auto_update]
    logger.info("update auto_updatable_candidates=%d only=%s", len(candidates), only or "-")
    if only:
        candidates = [
            candidate for candidate in candidates
            if candidate.item.id == only or candidate.item.name == only
        ]
    if not candidates:
        console.print("No auto-updatable candidates found.")
        return
    for candidate in candidates:
        _print_candidate_detail(candidate)
        if not typer.confirm("Run this update command?", default=False):
            logger.info("update skipped command=%s", " ".join(candidate.command))
            continue
        logger.info("update executing command=%s", " ".join(candidate.command))
        subprocess.run(candidate.command, check=False)


def run_scan(apps_only: bool = False, plugin_names: list[str] | None = None) -> ScanResult:
    system = detect_system()
    logger.info("scan start os=%s version=%s arch=%s apps_only=%s plugins=%s", system.os_name, system.os_version, system.arch, apps_only, plugin_names or "default")
    if plugin_names:
        logger.info("scan explicit plugins requested; skipping Applications scanner")
        applications = []
    else:
        logger.info("scan applications paths=%s", system.applications_paths)
        applications = scan_applications(system.applications_paths)
        logger.info("scan applications found=%d", len(applications))
    result = ScanResult(system=system, applications=applications)
    if apps_only:
        logger.info("scan apps_only=true skipping plugins")
        return result
    plugins = enabled_plugins(plugin_names)
    if plugins:
        _run_plugins_concurrent(plugins, system, result)
    logger.info("scan done applications=%d candidates=%d skipped=%d", len(result.applications), len(result.candidates), len(result.skipped))
    return result


def _run_plugins_concurrent(plugins: list, system, result: ScanResult) -> None:
    with ThreadPoolExecutor(max_workers=len(plugins)) as pool:
        futures = {pool.submit(_run_one_plugin, plugin, system): plugin for plugin in plugins}
        for future in as_completed(futures):
            plugin = futures[future]
            try:
                candidates, skipped = future.result()
                logger.info("scan plugin done name=%s candidates=%d skipped=%d", plugin.name, len(candidates), len(skipped))
                result.candidates.extend(candidates)
                result.skipped.extend(skipped)
            except Exception as exc:
                logger.warning("scan plugin failed name=%s: %s", plugin.name, exc)


def _run_one_plugin(plugin, system) -> tuple[list[UpdateCandidate], list[str]]:
    logger.info("scan plugin start name=%s", plugin.name)
    return plugin.scan(system)


def _split_plugins(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _print_advise_result(result: ScanResult, researched_ids: set[str]) -> None:
    console.print(
        f"OS: {result.system.os_name} {result.system.os_version} | "
        f"Arch: {result.system.arch} | Paths: {', '.join(result.system.applications_paths)}"
    )
    table = Table(expand=True)
    table.add_column("ID", ratio=2, no_wrap=True, overflow="ellipsis")
    table.add_column("Software", ratio=3, no_wrap=True, overflow="ellipsis")
    table.add_column("Source", no_wrap=True)
    table.add_column("Current", no_wrap=True, overflow="ellipsis")
    table.add_column("Latest", no_wrap=True, overflow="ellipsis")
    table.add_column("Action", no_wrap=True)
    candidate_item_ids = {candidate.item.id for candidate in result.candidates}
    for item in result.applications:
        if item.id in candidate_item_ids:
            continue
        if item.id in researched_ids:
            table.add_row(item.id, item.name, item.source.value, item.current_version or "unknown", "up to date", "—")
        else:
            table.add_row(item.id, item.name, item.source.value, item.current_version or "unknown", "failed", "retry")
    for candidate in result.candidates:
        table.add_row(
            candidate.item.id,
            candidate.item.name,
            candidate.item.source.value,
            candidate.item.current_version or "unknown",
            candidate.latest_version or "unknown",
            candidate.recommended_action,
        )
    console.print(table)
    for skipped in result.skipped:
        console.print(f"Skipped: {skipped}")


def _print_candidate_detail(candidate: UpdateCandidate) -> None:
    table = Table(expand=True)
    table.add_column("Key", no_wrap=True)
    table.add_column("Value", ratio=3)
    table.add_row("Software", candidate.item.name)
    table.add_row("Source", candidate.item.source.value)
    table.add_row("Current", candidate.item.current_version or "unknown")
    table.add_row("Latest", candidate.latest_version or "unknown")
    table.add_row("Impact", candidate.dependency_impact.impact_level)
    table.add_row("Used by", ", ".join(candidate.dependency_impact.used_by) or "none")
    table.add_row("Depends on", ", ".join(candidate.dependency_impact.depends_on) or "none")
    table.add_row("Advice", candidate.ai_summary or candidate.recommended_action)
    table.add_row("Command", " ".join(candidate.command))
    console.print(table)


if __name__ == "__main__":
    app()
