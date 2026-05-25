"""Config subcommands: manage, show, path, test."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ..store.config_store import CONFIG_PATH, load_config, require_config, save_config
from ._output import exit_with_error, print_json_success

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

    if choice == "key":
        provider = current.provider
        model = _find_model(provider, current.model) or provider.models[0]
        protocol = getattr(current, "protocol", "openai")
        url = getattr(current, "url", "")
        api_key = _ask_api_key(provider, current)
        console.print()
        _test_and_save(provider, model, api_key, protocol, url)
        return

    # "provider" or "everything": wizard with back support
    provider, model = None, None
    protocol = "openai"
    url = ""
    api_key = current.api_key if choice == "provider" else ""

    step = 0  # 0=provider, 1=protocol, 2=url, 3=key, 4=done
    while step < 4:
        if step == 0:
            result = _pick_provider_and_model(current)
            if result is None:
                if current:
                    # Back to "What to modify" menu
                    _show_current_config(current)
                    choice = _ask_what_to_modify()
                    if choice == "cancel":
                        raise _ConfigCancelled()
                    if choice == "key":
                        provider = current.provider
                        model = _find_model(provider, current.model) or provider.models[0]
                        protocol = getattr(current, "protocol", "openai")
                        url = getattr(current, "url", "")
                        api_key = _ask_api_key(provider, current)
                        console.print()
                        _test_and_save(provider, model, api_key, protocol, url)
                        return
                    # choice is "provider" or "everything" — continue wizard
                    api_key = current.api_key if choice == "provider" else ""
                continue
            provider, model = result
            step = 1
        elif step == 1:
            result = _pick_protocol(provider, current)
            if result == "back":
                step = 0
                continue
            protocol = result
            step = 2
        elif step == 2:
            result = _ask_url(provider, protocol, current)
            if result == "back":
                step = 1
                continue
            url = result
            step = 3
        elif step == 3:
            if choice == "everything":
                api_key = _ask_api_key(provider, current)
            step = 4

    console.print()
    _test_and_save(provider, model, api_key, protocol, url)


def _safe_ask_number(prompt: str, choices: list[str]) -> int:
    """Wrapper around IntPrompt.ask that handles cancellation."""
    from rich.prompt import IntPrompt

    try:
        return IntPrompt.ask(prompt, choices=choices, show_choices=False)
    except (KeyboardInterrupt, EOFError):
        raise _ConfigCancelled()


def _find_model(provider, model_id: str):
    """Find a ModelInfo by id, or return None."""
    for m in provider.models:
        if m.id == model_id:
            return m
    return None


def _show_current_config(current) -> None:
    """Display the current LLM configuration."""
    console.print()
    console.print("[bold]Current configuration:[/bold]")
    console.print(f"  Provider: [cyan]{current.provider.name}[/cyan]")
    console.print(f"  Model:    [cyan]{current.model}[/cyan]")
    protocol = getattr(current, "protocol", "openai")
    console.print(f"  Protocol: [cyan]{protocol}[/cyan]")
    console.print(f"  URL:      [cyan]{current.url}[/cyan]")
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
    console.print("  4. Cancel (Ctrl+C)")
    console.print()

    idx = _safe_ask_number("Enter choice", ["1", "2", "3", "4"])
    return {1: "provider", 2: "key", 3: "everything", 4: "cancel"}[idx]


def _pick_provider_and_model(current):
    """Walk through provider and model selection. Returns (provider, model) or None on back."""
    from ..providers import PROVIDERS

    current_provider_id = current.provider.id if current else None

    while True:
        console.print()
        console.print("[bold]Select an LLM provider (Ctrl+C to cancel):[/bold]")
        if current_provider_id:
            console.print(f"  [dim]Current: {current.provider.name}[/dim]")
        console.print("  [dim]0. Back[/dim]")
        for i, p in enumerate(PROVIDERS, 1):
            marker = " [dim](current)[/dim]" if p.id == current_provider_id else ""
            console.print(f"  {i}. {p.name}  [dim]({len(p.models)} models)[/dim]{marker}")
        console.print()

        idx = _safe_ask_number(
            "Enter provider number",
            [str(i) for i in range(0, len(PROVIDERS) + 1)],
        )
        if idx == 0:
            return None
        provider = PROVIDERS[idx - 1]
        console.print(f"  [green]{provider.name}[/green] selected.")
        console.print()

        current_model_id = current.model if current and current.provider.id == provider.id else None

        console.print(f"[bold]Select a model for {provider.name} (Ctrl+C to cancel):[/bold]")
        if current_model_id:
            current_model_name = next((m.name for m in provider.models if m.id == current_model_id), current_model_id)
            console.print(f"  [dim]Current: {current_model_name}[/dim]")
        console.print("  [dim]0. Back[/dim]")
        for i, m in enumerate(provider.models, 1):
            cur = " [dim](current)[/dim]" if m.id == current_model_id else ""
            console.print(f"  {i}. {m.name}{cur}")
        console.print()

        model_idx = _safe_ask_number(
            "Enter model number",
            [str(i) for i in range(0, len(provider.models) + 1)],
        )
        if model_idx == 0:
            continue  # back to provider selection
        model = provider.models[model_idx - 1]
        console.print(f"  [green]{model.name}[/green] selected.")
        return provider, model


def _pick_protocol(provider, current) -> str:
    """Show protocol selection. Auto-selects when only one is available. Returns 'back' to go back."""
    current_protocol = getattr(current, "protocol", "openai") if current else "openai"

    console.print()
    if len(provider.protocols) == 1:
        proto = provider.protocols[0]
        console.print(f"[bold]Protocol for {provider.name}:[/bold] [cyan]{proto}[/cyan]")
        console.print("  [dim]0. Back[/dim]")
        console.print()
        idx = _safe_ask_number("Enter choice", ["0", "1"])
        if idx == 0:
            return "back"
        return proto

    console.print(f"[bold]Select protocol for {provider.name} (Ctrl+C to cancel):[/bold]")
    if current:
        console.print(f"  [dim]Current: {current_protocol}[/dim]")
    console.print("  [dim]0. Back[/dim]")
    for i, proto in enumerate(provider.protocols, 1):
        cur = " [dim](current)[/dim]" if proto == current_protocol else ""
        console.print(f"  {i}. {proto}{cur}")
    console.print()

    idx = _safe_ask_number(
        "Enter protocol number",
        [str(i) for i in range(0, len(provider.protocols) + 1)],
    )
    if idx == 0:
        return "back"
    chosen = provider.protocols[idx - 1]
    console.print(f"  [green]{chosen}[/green] selected.")
    return chosen


def _ask_url(provider, protocol: str, current) -> str:
    """Ask user for the endpoint URL. Empty = keep current, '-' = reset to default."""
    from ..providers import get_protocol_url

    current_url = (current.url if current and current.provider.id == provider.id
                   else get_protocol_url(provider, protocol))
    default_url = get_protocol_url(provider, protocol)

    console.print()
    console.print(f"[bold]Endpoint URL for {provider.name} ({protocol})[/bold]")
    console.print(f"  [dim]Default: {default_url}[/dim]")
    if current_url != default_url:
        console.print(f"  [dim]Current: {current_url}[/dim]")
    console.print("  [dim](leave empty to keep current, '-' = reset to default, 'back' = previous step)[/dim]")

    try:
        url = typer.prompt("URL", default=current_url, show_default=False).strip()
    except (KeyboardInterrupt, EOFError):
        raise _ConfigCancelled()

    if url == "back":
        return "back"
    if url == "-":
        console.print(f"  [dim]Reset to default ({default_url})[/dim]")
        return default_url
    console.print(f"  [green]{url}[/green]")
    return url


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


def _test_and_save(provider, model, api_key, protocol: str = "openai",
                   url: str = "") -> None:
    """Test the connection and save the config."""
    import httpx

    from ..llm import LLMRequestError, get_client
    from ..store.config_store import ProviderConfig

    console.print()
    console.print(f"[bold]Testing connection to {provider.name}...[/bold]")
    try:
        test_config = ProviderConfig(
            provider=provider,
            model=model.id,
            api_key=api_key,
            protocol=protocol,
            url=url,
        )
        test_client = get_client(test_config)
        test_text = test_client.test_connection()
        test_client.close()
        console.print(f"  [green]Connection OK:[/green] {test_text.strip()}")
    except EOFError:
        raise _ConfigCancelled()
    except KeyboardInterrupt:
        raise _ConfigCancelled()
    except (LLMRequestError, ValueError, NotImplementedError, httpx.RequestError) as exc:
        console.print(f"  [yellow]Warning:[/yellow] test request failed: {exc}")
        try:
            confirmed = typer.confirm("Save config anyway?", default=False)
        except (KeyboardInterrupt, EOFError):
            raise _ConfigCancelled()
        if not confirmed:
            raise _ConfigCancelled()

    save_config(provider.id, model.id, api_key, protocol=protocol, url=url)
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
            provider=llm.provider.id,
            model=llm.model,
            protocol=llm.protocol,
            url=llm.url,
            key_suffix=key_suffix if llm.api_key else None,
            key_source=llm.api_key_source,
        )
        return

    table = Table("Key", "Value")
    table.add_row("Provider", llm.provider.name)
    table.add_row("Model", llm.model)
    table.add_row("Protocol", llm.protocol)
    table.add_row("URL", llm.url)
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
    from ..llm import LLMRequestError, get_client

    try:
        config = require_config()
        client = get_client(config)
        text = client.test_connection()
        client.close()
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
            url=config.url,
            response=text.strip(),
        )
        return

    console.print(f"Provider: {config.provider.name}")
    console.print(f"Model: {config.model}")
    console.print(f"URL: {config.url}")
    console.print(f"LLM test response: {text.strip()}")
