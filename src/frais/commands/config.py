"""Config subcommands: manage, show, path, test."""

from __future__ import annotations

import logging
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ..config import CONFIG_PATH, load_config, require_config, save_config
from ._output import exit_with_error, print_json_success

logger = logging.getLogger(__name__)
console = Console()


class _ConfigCancelled(typer.Exit):
    """Raised when the user cancels config manage mid-flow."""
    def __init__(self):
        super().__init__(0)


def config_manage() -> None:
    """Interactively configure or modify the LLM provider.

    If a config already exists, shows current settings and lets you choose
    what to change. Otherwise walks through full setup.

    Press Ctrl+C or choose Cancel at any step to abort without saving.

    This command is interactive only — ``--json`` is not supported.

    Example:
      frais config manage
    """
    try:
        _config_manage_flow()
    except _ConfigCancelled:
        console.print()
        console.print("[dim]Configuration cancelled, nothing saved.[/dim]")
    except (KeyboardInterrupt, EOFError):
        console.print()
        console.print("[dim]Configuration cancelled, nothing saved.[/dim]")


def _config_manage_flow() -> None:
    """Internal flow for config manage. Raises _ConfigCancelled on abort."""
    current = load_config()

    if current:
        _show_current_config(current)
        choice = _ask_what_to_modify()
        if choice == "cancel":
            raise _ConfigCancelled()
    else:
        choice = "everything"

    if choice in ("provider", "everything"):
        provider, model = _pick_provider_and_model(current)
    else:
        provider = current.provider
        model = next((m for m in provider.models if m.id == current.model), provider.models[0])

    if choice in ("key", "everything"):
        api_key = _ask_api_key(provider, current)
    else:
        api_key = current.api_key

    console.print()
    _test_and_save(provider, model, api_key)


def _safe_ask_number(prompt: str, choices: list[str]) -> int:
    """Wrapper around IntPrompt.ask that handles cancellation."""
    from rich.prompt import IntPrompt

    try:
        return IntPrompt.ask(prompt, choices=choices, show_choices=False)
    except (KeyboardInterrupt, EOFError):
        raise _ConfigCancelled()


def _show_current_config(current) -> None:
    """Display the current LLM configuration."""
    console.print()
    console.print("[bold]Current configuration:[/bold]")
    console.print(f"  Provider: [cyan]{current.provider.name}[/cyan]")
    console.print(f"  Model:    [cyan]{current.model}[/cyan]")
    masked = "***" + current.api_key[-4:] if len(current.api_key) >= 4 else "***"
    console.print(f"  API key:  [dim]{masked}[/dim]")
    console.print()


def _ask_what_to_modify() -> str:
    """Ask the user what part of the config they want to change."""
    console.print()
    console.print("[bold]What would you like to modify?[/bold]")
    console.print("  1. Provider & Model")
    console.print("  2. API Key")
    console.print("  3. Everything (full reconfiguration)")
    console.print("  4. Cancel (Esc / Ctrl+C)")
    console.print()

    idx = _safe_ask_number("Enter choice", ["1", "2", "3", "4"])
    return {1: "provider", 2: "key", 3: "everything", 4: "cancel"}[idx]


def _pick_provider_and_model(current):
    """Walk through provider and model selection. Returns (provider, model)."""
    from ..providers import PROVIDERS

    current_provider_id = current.provider.id if current else None

    console.print()
    console.print("[bold]Select an LLM provider (Ctrl+C to cancel):[/bold]")
    if current_provider_id:
        console.print(f"  [dim]Current: {current.provider.name}[/dim]")
    console.print()
    for i, p in enumerate(PROVIDERS, 1):
        marker = " [dim](current)[/dim]" if p.id == current_provider_id else ""
        console.print(f"  {i}. {p.name}  [dim]({len(p.models)} models)[/dim]{marker}")
    console.print()

    idx = _safe_ask_number(
        "Enter provider number",
        [str(i) for i in range(1, len(PROVIDERS) + 1)],
    )
    provider = PROVIDERS[idx - 1]
    console.print(f"  [green]{provider.name}[/green] selected.")
    console.print()

    current_model_id = current.model if current and current.provider.id == provider.id else None

    console.print(f"[bold]Select a model for {provider.name} (Ctrl+C to cancel):[/bold]")
    if current_model_id:
        current_model_name = next((m.name for m in provider.models if m.id == current_model_id), current_model_id)
        console.print(f"  [dim]Current: {current_model_name}[/dim]")
    console.print()
    for i, m in enumerate(provider.models, 1):
        default_mark = " [dim](thinking by default)[/dim]" if m.thinking_default else ""
        cur = " [dim](current)[/dim]" if m.id == current_model_id else ""
        console.print(f"  {i}. {m.name}{default_mark}{cur}")
    console.print()

    model_idx = _safe_ask_number(
        "Enter model number",
        [str(i) for i in range(1, len(provider.models) + 1)],
    )
    model = provider.models[model_idx - 1]
    console.print(f"  [green]{model.name}[/green] selected.")

    return provider, model


def _ask_api_key(provider, current) -> str:
    """Prompt for a new API key. Empty input keeps the existing key."""
    from getpass import getpass

    console.print()
    if current:
        masked = "***" + current.api_key[-4:] if len(current.api_key) >= 4 else "(not set)"
        console.print(f"[bold]Enter API key for {provider.name} (Ctrl+C to cancel):[/bold]")
        console.print(f"  [dim]Current: {masked}[/dim]")
        console.print("  [dim](leave empty to keep current key)[/dim]")
    else:
        console.print(f"[bold]Enter API key for {provider.name} (Ctrl+C to cancel):[/bold]")

    try:
        api_key = getpass("API key (input hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        raise _ConfigCancelled()

    if not api_key:
        if current and current.api_key:
            console.print("  [dim]Keeping current API key.[/dim]")
            return current.api_key
        console.print("[red]API key cannot be empty.[/red]")
        raise typer.Exit(1)
    console.print("  [green]API key received.[/green]")
    return api_key


def _test_and_save(provider, model, api_key) -> None:
    """Test the connection and save the config."""
    from ..llm import LLMClient
    from ..config import ProviderConfig

    console.print()
    console.print(f"[bold]Testing connection to {provider.name}...[/bold]")
    try:
        test_config = ProviderConfig(
            provider=provider,
            model=model.id,
            api_key=api_key,
        )
        test_text = LLMClient(test_config).test_connection()
        console.print(f"  [green]Connection OK:[/green] {test_text.strip()}")
    except EOFError:
        raise _ConfigCancelled()
    except KeyboardInterrupt:
        raise _ConfigCancelled()
    except Exception as exc:
        console.print(f"  [yellow]Warning:[/yellow] test request failed: {exc}")
        try:
            confirmed = typer.confirm("Save config anyway?", default=False)
        except (KeyboardInterrupt, EOFError):
            raise _ConfigCancelled()
        if not confirmed:
            raise _ConfigCancelled()

    save_config(provider.id, model.id, api_key)
    console.print()
    console.print(f"[green]Config saved to {CONFIG_PATH}[/green]")


def config_show(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Show current LLM provider config with secrets redacted.

    The API key is never printed; only presence and a final 4-character suffix
    are shown when available.

    Example:
      frais config show
    """
    llm = load_config()
    if not llm:
        if json_output:
            print_json_success(configured=False)
            return
        console.print("[dim]Not configured. Run `frais config manage` to set up.[/dim]")
        return

    if json_output:
        key_suffix = "***" + llm.api_key[-4:] if len(llm.api_key) >= 4 else "***"
        print_json_success(
            configured=True,
            provider=llm.provider.name,
            model=llm.model,
            key_suffix=key_suffix if llm.api_key else None,
            key_source=llm.api_key_source,
        )
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


def config_path(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Print the default BYOK config file path.

    Example:
      frais config path
    """
    if json_output:
        print_json_success(path=str(CONFIG_PATH))
        return
    console.print(str(CONFIG_PATH))


def config_test(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output structured JSON (for agent consumption)."),
    ] = False,
) -> None:
    """Send a minimal LLM request to validate provider settings.

    This never prints the API key. It reports the provider, model,
    chat completions URL, and a short success or error message.

    Example:
      frais config test
    """
    from ..llm import LLMClient, LLMRequestError

    try:
        config = require_config()
        text = LLMClient(config).test_connection()
    except ValueError as exc:
        exit_with_error(str(exc), json_output, exit_code=2,
                        reason="config_missing",
                        hint="Run `frais config manage` to set up your provider and API key.")
    except LLMRequestError as exc:
        exit_with_error(str(exc), json_output, exit_code=2,
                        reason="connection_error",
                        hint="Check your API key and network connection, then try again.")

    if json_output:
        print_json_success(
            provider=config.provider.name,
            model=config.model,
            url=config.provider.chat_url,
            response=text.strip(),
        )
        return

    console.print(f"Provider: {config.provider.name}")
    console.print(f"Model: {config.model}")
    console.print(f"Chat completions URL: {config.provider.chat_url}")
    console.print(f"LLM test response: {text.strip()}")
