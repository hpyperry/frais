from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console

from ..config import require_config
from ..models import UpdateCandidate
from ._output import exit_with_error, print_json_success

if TYPE_CHECKING:
    from ..llm import LLMClient

logger = logging.getLogger(__name__)
console = Console()


_SUMMARIZE_PROMPT = (
    "You are helping a macOS user decide whether to update installed software. "
    "Write a concise update recommendation in Chinese.\n"
    "\n"
    "Rules:\n"
    "- Output 3-4 short bullet lines (each starting with \"- \"), no preamble or closing.\n"
    "- Use **bold** for version numbers, risk levels, and key actions.\n"
    "- Mention: what changed, risk level, dependency impact (if any), and a clear recommendation.\n"
    "- If the evidence includes URLs, reference the most credible one.\n"
    "- Never invent version numbers, CVEs, or changelog details not present in the data.\n"
    "- If evidence is weak or missing, say so honestly — prefer \"信息不足\" over guessing."
)


def build_summary_prompt(candidate: UpdateCandidate) -> str:
    """Build the user prompt for generating an update recommendation."""
    d = candidate.to_dict()
    item = d.get("item", {})
    dep = d.get("dependency_impact", {})
    return (
        f"{_SUMMARIZE_PROMPT}\n\n"
        f"Name: {item.get('name', 'unknown')}\n"
        f"Type: {item.get('kind', 'unknown')} ({item.get('source', 'unknown')})\n"
        f"Current version: {item.get('current_version', 'unknown')}\n"
        f"Latest version: {d.get('latest_version', 'unknown')}\n"
        f"Risk level: {d.get('risk_level', 'unknown')}\n"
        f"Auto-update available: {d.get('can_auto_update', False)}\n"
        f"Update command: {' '.join(d.get('command', [])) or '(manual)'}\n"
        f"Dependencies: {len(dep.get('depends_on', []))} packages\n"
        f"Used by: {len(dep.get('used_by', []))} packages\n"
        f"Evidence: {json.dumps(d.get('evidence', []), ensure_ascii=False)}\n"
        f"Release notes: {d.get('release_notes') or '(none)'}"
    )


def summarize_candidate(llm: "LLMClient", candidate: UpdateCandidate) -> str:
    """Generate a Chinese-language update recommendation for a candidate."""
    prompt = build_summary_prompt(candidate)
    return llm.chat("", prompt, max_tokens=500)


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
        exit_with_error("No scan cache found.", json_output,
                        reason="no_cache",
                        hint="Run `frais scan --json` or `frais advise --json` first to generate a scan cache.")

    try:
        data = json.loads(_ADVICE_CACHE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        exit_with_error(f"Failed to read scan cache: {exc}", json_output,
                        reason="cache_read_error",
                        hint="The scan cache file is corrupted. Run `frais scan --json` to rebuild it.")

    from ..llm import get_client
    from ..plugins.registry import all_plugins

    candidate: UpdateCandidate | None = None
    plugin_name: str | None = None
    if "plugin_results" in data:
        for pname, pr in data["plugin_results"].items():
            for raw in pr.get("candidates", []):
                if raw.get("item", {}).get("id") == item_id:
                    try:
                        candidate = UpdateCandidate.from_dict(raw)
                    except (KeyError, TypeError, ValueError):
                        continue
                    plugin_name = pname
                    break
            if candidate:
                break

    if candidate is None:
        exit_with_error(f"No candidate found for: {item_id}", json_output,
                        reason="candidate_not_found",
                        hint="Run `frais scan --json` to see available candidate IDs.",
                        item_id=item_id)

    try:
        config = require_config()
        llm = get_client(config)
    except ValueError as exc:
        exit_with_error(str(exc), json_output, exit_code=2,
                        reason="config_missing",
                        hint="Run `frais config manage` to set up your provider and API key.")

    plugin = all_plugins().get(plugin_name or "")
    if plugin is None:
        exit_with_error(f"Plugin not found: {plugin_name}", json_output,
                        reason="plugin_not_found",
                        hint="Run `frais plugins list --json` to see available plugins.",
                        plugin_name=plugin_name)

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
