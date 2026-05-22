from __future__ import annotations

import json
import logging
from typing import Annotated

import typer
from rich.console import Console

from ..config import require_config
from ..models import UpdateCandidate

logger = logging.getLogger(__name__)
console = Console()


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
    from ..cli import _ADVICE_CACHE

    if not _ADVICE_CACHE.exists():
        console.print("No scan cache found. Run [bold]frais advise[/bold] or [bold]frais scan[/bold] first.")
        raise typer.Exit(1)

    try:
        data = json.loads(_ADVICE_CACHE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"Failed to read scan cache: {exc}")
        raise typer.Exit(1)

    from ..llm import LLMClient
    from ..plugins.registry import all_plugins

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

    try:
        for pname, pr in data.get("plugin_results", {}).items():
            for raw in pr.get("candidates", []):
                if raw.get("item", {}).get("id") == item_id:
                    raw["ai_summary"] = summary
                    _ADVICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
                    tmp_path = _ADVICE_CACHE.with_suffix(".tmp")
                    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                    tmp_path.replace(_ADVICE_CACHE)
                    break
            else:
                continue
            break
    except OSError as exc:
        logger.warning("failed to update scan cache: %s", exc)

    if json_output:
        console.print_json(json.dumps({"item_id": item_id, "ai_summary": summary}, ensure_ascii=False))
    else:
        console.print(summary or "(no summary generated)")
