from __future__ import annotations

import logging
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ..store.config_store import load_config
from ._output import print_json_success

logger = logging.getLogger(__name__)
console = Console()


def doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Show runtime readiness without changing the system.

    Prints detected OS version, CPU architecture, scanned Applications paths,
    plugin availability, and redacted BYOK status.
    """
    from ..plugins.registry import all_plugins
    from ..system import detect_system

    system = detect_system()
    llm_cfg = load_config()
    logger.info("doctor system=%s %s arch=%s", system.os_name, system.os_version, system.arch)
    if llm_cfg:
        logger.info("doctor llm_ready=%s provider=%s", llm_cfg.is_ready, llm_cfg.provider.name)

    if json_output:
        plugins_data = _plugins_json()
        llm_data = _llm_json() if llm_cfg else None
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
        table.add_row("LLM provider", llm_cfg.provider.name)
        table.add_row("LLM model", llm_cfg.model)
        table.add_row("LLM protocol", llm_cfg.protocol)
        table.add_row("LLM base URL",
                      llm_cfg.base_url_override or f"{llm_cfg.provider.base_url} (default)")
        table.add_row("LLM key", _mask_key(llm_cfg.api_key))
    else:
        table.add_row("LLM", "not configured (run `frais config manage`)")
    console.print(table)


def _plugins_json() -> dict[str, dict[str, str]]:
    from ..plugins.registry import all_plugins

    plugins_data: dict[str, dict[str, str]] = {}
    for name, plugin in all_plugins().items():
        plugins_data[name] = {
            "available": "yes" if plugin.is_available() else "no",
            "default": "enabled" if plugin.enabled_by_default else "disabled",
        }
    return plugins_data


def _llm_json() -> dict[str, str | bool] | None:
    llm_cfg = load_config()
    if not llm_cfg:
        return None
    return {
        "configured": llm_cfg.is_ready,
        "provider": llm_cfg.provider.name,
        "model": llm_cfg.model,
        "protocol": llm_cfg.protocol,
        "base_url": llm_cfg.base_url_override or llm_cfg.provider.base_url,
        "key_suffix": _mask_key(llm_cfg.api_key),
    }


def _mask_key(api_key: str) -> str:
    if len(api_key) >= 4:
        return "***" + api_key[-4:]
    return "***"
