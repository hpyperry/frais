from __future__ import annotations

import json
import logging
from typing import Annotated

import typer
from rich.console import Console

from ..config import require_config
from ..models import UpdateCandidate
from ._output import exit_with_error, print_json_success

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
        exit_with_error("No scan cache found. Run `frais advise` or `frais scan` first.", json_output)

    try:
        data = json.loads(_ADVICE_CACHE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        exit_with_error(f"Failed to read scan cache: {exc}", json_output)

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
        exit_with_error(f"No candidate found for: {item_id}", json_output)

    try:
        config = require_config()
        llm = LLMClient(config)
    except ValueError as exc:
        exit_with_error(str(exc), json_output, exit_code=2)

    plugin = all_plugins().get(plugin_name or "")
    if plugin is None:
        exit_with_error(f"Plugin not found: {plugin_name}", json_output)

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
        print_json_success(item_id=item_id, ai_summary=summary)
    else:
        console.print(summary or "(no summary generated)")
