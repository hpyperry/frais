from __future__ import annotations

import json
import logging
from typing import Annotated, Any

import typer
from rich.console import Console

from ..models import SourceKind, UpdateCandidate
from ..paths import ADVICE_CACHE
from ..plugins.base import ScannerPlugin

logger = logging.getLogger(__name__)
console = Console()


def _load_advice_cache_or_exit() -> Any:
    """Load the advice cache, or print error and raise Exit."""
    if not ADVICE_CACHE.exists():
        console.print("No advice cache found. Run [bold]frais advise[/bold] first.")
        raise typer.Exit(1)
    try:
        return json.loads(ADVICE_CACHE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"Failed to read advice cache: {exc}")
        raise typer.Exit(1)


def _parse_candidates_from_cache(data: Any) -> tuple[list[UpdateCandidate], dict[str, str]]:
    """Parse UpdateCandidate list and build id→plugin_name map from cache."""
    plugin_map: dict[str, str] = {}
    raw_candidates: list[dict[str, Any]] = []
    plugin_results: dict[str, Any] = data.get("plugin_results", {})
    for plugin_name, pr in plugin_results.items():
        for raw_cand in pr.get("candidates", []):
            item_data: dict[str, Any] = raw_cand.get("item", {})
            plugin_map[item_data.get("id", "")] = str(plugin_name)
        raw_candidates.extend(pr.get("candidates", []))

    candidates: list[UpdateCandidate] = []
    for raw in raw_candidates:
        try:
            candidates.append(UpdateCandidate.from_dict(raw))
        except Exception as exc:
            logger.warning("failed to parse cached candidate: %s", exc)
    return candidates, plugin_map


def _filter_candidates(candidates: list[UpdateCandidate], only: str | None) -> list[UpdateCandidate]:
    """Filter candidates by exact id or name match."""
    if not only:
        return candidates
    return [c for c in candidates if c.item.id == only or c.item.name == only]


def _execute_update_loop(
    candidates: list[UpdateCandidate],
    plugin_map: dict[str, str],
    plugins: dict[str, ScannerPlugin],
) -> None:
    """Interactive confirmation loop: display, confirm, execute."""
    for candidate in candidates:
        console.print()
        console.print(f"  [bold]{candidate.item.name}[/bold]  [dim]({candidate.item.id})[/dim]")
        console.print(
            f"  {candidate.item.current_version or 'unknown'} → "
            f"[green]{candidate.latest_version or 'unknown'}[/green]"
        )
        if candidate.ai_summary:
            from rich.markdown import Markdown
            console.print()
            console.print("  [bold cyan]AI Analysis[/]")
            console.print(Markdown(candidate.ai_summary))
        else:
            console.print()
            console.print(f"  [dim]No AI summary yet — `frais summarize {candidate.item.id}`[/dim]")

        if candidate.can_auto_update and candidate.item.source != SourceKind.APP_STORE:
            console.print(f"    [dim]cmd: {' '.join(candidate.command)}[/dim]")
        elif not candidate.can_auto_update:
            console.print("    [dim]manual update[/dim]")

        if not typer.confirm("  Proceed?", default=False):
            logger.info("update skipped name=%s", candidate.item.name)
            continue

        plugin_name = plugin_map.get(candidate.item.id)
        plugin = plugins.get(plugin_name) if plugin_name else None
        if plugin is not None:
            ok = plugin.update(candidate)
            logger.info("update executed plugin=%s name=%s ok=%s", plugin_name, candidate.item.name, ok)


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
    from ..plugins.registry import all_plugins

    data = _load_advice_cache_or_exit()
    candidates, plugin_map = _parse_candidates_from_cache(data)

    candidates = _filter_candidates(candidates, only)
    if not candidates:
        console.print("No update candidates found.")
        return

    plugins = all_plugins()
    _execute_update_loop(candidates, plugin_map, plugins)
