from __future__ import annotations

import json
import logging
from typing import Annotated

import typer
from rich.console import Console
from rich.padding import Padding

from ..models import SourceKind, UpdateCandidate

logger = logging.getLogger(__name__)
console = Console()


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
    from ..cli import _ADVICE_CACHE

    if not _ADVICE_CACHE.exists():
        console.print("No advice cache found. Run [bold]frais advise[/bold] first.")
        raise typer.Exit(1)

    try:
        data = json.loads(_ADVICE_CACHE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"Failed to read advice cache: {exc}")
        raise typer.Exit(1)

    from ..plugins.registry import all_plugins

    plugin_map: dict[str, str] = {}
    if "plugin_results" in data:
        for plugin_name, pr in data["plugin_results"].items():
            for raw_cand in pr.get("candidates", []):
                item_data = raw_cand.get("item", {})
                plugin_map[item_data.get("id", "")] = plugin_name

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
        console.print(f"  [bold]{candidate.item.name}[/bold]  [dim]({candidate.item.id})[/dim]")
        console.print(
            f"  {candidate.item.current_version or 'unknown'} → "
            f"[green]{candidate.latest_version or 'unknown'}[/green]"
        )
        if candidate.ai_summary:
            console.print()
            console.print(f"  [bold cyan]AI Analysis[/]")
            console.print(Padding(candidate.ai_summary, (0, 0, 0, 4)))
        else:
            console.print()
            console.print(f"  [dim]No AI summary yet — `frais summarize {candidate.item.id}`[/dim]")

        if candidate.can_auto_update and candidate.item.source != SourceKind.APP_STORE:
            console.print(f"    [dim]cmd: {' '.join(candidate.command)}[/dim]")
        elif not candidate.can_auto_update:
            console.print(f"    [dim]manual update[/dim]")

        if not typer.confirm("  Proceed?", default=False):
            logger.info("update skipped name=%s", candidate.item.name)
            continue

        plugin_name = plugin_map.get(candidate.item.id)
        plugin = plugins.get(plugin_name) if plugin_name else None
        if plugin:
            ok = plugin.update(candidate)
            logger.info("update executed plugin=%s name=%s ok=%s", plugin_name, candidate.item.name, ok)
