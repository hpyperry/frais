// config commands — matches Python's frais/commands/config.py.
use super::JsonFlag;
use crate::store::config_store::save_config;
use std::collections::BTreeMap;

/// Shorten a key source for display.
fn short_key_source(source: Option<&str>) -> String {
    match source {
        Some("FRAIS_LLM_API_KEY") | Some("MIMO_API_KEY") | Some("OPENAI_API_KEY") => {
            "env var".to_string()
        }
        Some(s) if s.ends_with("config.toml") => "config file".to_string(),
        Some(s) => s.to_string(),
        None => "unknown".to_string(),
    }
}

pub fn show(args: JsonFlag) -> Result<(), String> {
    let config = crate::store::config_store::load_config(&crate::paths::config_path());
    let json_output = args.json();

    if json_output {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        if let Some(c) = &config {
            extra.insert("configured".into(), serde_json::Value::Bool(true));
            extra.insert("provider".into(), c.provider.clone().into());
            extra.insert("model".into(), c.model.clone().into());
            extra.insert("protocol".into(), c.protocol.clone().into());
            extra.insert("url".into(), c.url.clone().into());
            extra.insert("language".into(), c.language.clone().into());
            extra.insert(
                "key_suffix".into(),
                if c.api_key.len() > 4 {
                    format!("***{}", &c.api_key[c.api_key.len() - 4..]).into()
                } else {
                    serde_json::Value::Null
                },
            );
            extra.insert(
                "key_source".into(),
                c.api_key_source.clone().unwrap_or_default().into(),
            );
        } else {
            extra.insert("configured".into(), serde_json::Value::Bool(false));
        }
        super::output::print_json_success(extra);
    } else {
        match &config {
            Some(c) => {
                let provider_name = c
                    .get_provider()
                    .map(|p| p.name)
                    .unwrap_or_else(|| c.provider.clone());
                super::output::info_row("Provider:", &provider_name);
                super::output::info_row("Model:", &c.model);
                super::output::info_row("Protocol:", &c.protocol);
                let endpoint = if c.url.is_empty() {
                    super::output::dim("(default)").to_string()
                } else {
                    c.url.clone()
                };
                super::output::info_row("Endpoint:", &endpoint);
                let lang_label = if c.language == "zh" {
                    "中文"
                } else {
                    "English"
                };
                super::output::info_row("Language:", lang_label);
                let masked = if c.api_key.len() > 4 {
                    format!("***{}", &c.api_key[c.api_key.len() - 4..])
                } else {
                    "***".into()
                };
                let source_note = short_key_source(c.api_key_source.as_deref());
                super::output::info_row_dim("Key:", &format!("{masked}  ({source_note})"));
            }
            None => {
                println!(
                    "  {} Run `frais config manage` to set up.",
                    super::output::dim("Not configured.")
                );
            }
        }
    }
    Ok(())
}

pub fn manage() -> Result<(), String> {
    match manage_flow() {
        Ok(()) => Ok(()),
        Err(ConfigCancelled) => {
            println!();
            println!("Configuration cancelled, nothing saved.");
            Ok(())
        }
    }
}

// ============================================================================
// Interactive config manage wizard — matches Python's _config_manage_flow
// ============================================================================

struct ConfigCancelled;

#[allow(clippy::needless_borrow)]
fn manage_flow() -> Result<(), ConfigCancelled> {
    let current = crate::store::config_store::load_config(&crate::paths::config_path());
    let providers = crate::providers::builtin_providers();

    if let Some(ref c) = current {
        show_current_config(c);
        match ask_what_to_modify()? {
            ModifyChoice::Cancel => return Err(ConfigCancelled),
            ModifyChoice::Key => {
                // Change only the API key, keep everything else
                let provider_name = c
                    .get_provider()
                    .map(|p| p.name.clone())
                    .unwrap_or_else(|| providers[0].name.clone());
                let api_key = ask_api_key(&provider_name, Some(c))?;
                println!();
                test_and_save(
                    &c.provider,
                    &c.model,
                    &api_key,
                    &c.protocol,
                    &c.url,
                    &c.language,
                )?;
                return Ok(());
            }
            ModifyChoice::Language => {
                // Change only the summary language — no API test needed
                let new_lang = ask_language(&c.language)?;
                println!();
                save_config(
                    &c.provider,
                    &c.model,
                    &c.api_key,
                    &c.protocol,
                    &c.url,
                    &new_lang,
                    &crate::paths::config_path(),
                )
                .map_err(|e| {
                    eprintln!(
                        "  {} Failed to save config: {}",
                        console::style("Error:").red(),
                        e
                    );
                    ConfigCancelled
                })?;
                println!();
                println!("{}", console::style("Language updated.").green());
                return Ok(());
            }
            ModifyChoice::Provider => {
                // Change provider/model/protocol/url, keep existing key
                return run_wizard(&providers, &current, "provider");
            }
            ModifyChoice::Everything => {
                // Full reconfiguration
                return run_wizard(&providers, &current, "everything");
            }
        }
    }

    // No existing config — full wizard
    run_wizard(&providers, &None, "everything")
}

enum ModifyChoice {
    Provider,
    Key,
    Language,
    Everything,
    Cancel,
}

fn show_current_config(config: &crate::store::config_store::ProviderConfig) {
    println!();
    println!("  {}", super::output::bold("Current configuration"));
    let provider = config
        .get_provider()
        .map(|p| p.name.clone())
        .unwrap_or_else(|| config.provider.clone());
    super::output::info_row("Provider:", &provider);
    super::output::info_row("Model:", &config.model);
    super::output::info_row("Protocol:", &config.protocol);
    let endpoint = if config.url.is_empty() {
        super::output::dim("(default)").to_string()
    } else {
        config.url.clone()
    };
    super::output::info_row("Endpoint:", &endpoint);
    let lang_label = if config.language == "zh" {
        "中文"
    } else {
        "English"
    };
    super::output::info_row("Language:", lang_label);
    let masked = if config.api_key.len() > 4 {
        format!("***{}", &config.api_key[config.api_key.len() - 4..])
    } else {
        "***".into()
    };
    let source_note = short_key_source(config.api_key_source.as_deref());
    super::output::info_row_dim("Key:", &format!("{masked}  ({source_note})"));
    println!();
}

fn ask_what_to_modify() -> Result<ModifyChoice, ConfigCancelled> {
    use dialoguer::Select;

    println!();
    println!("What would you like to change?");
    let items = &[
        "Provider & Model",
        "API Key",
        "Language",
        "Everything",
        "Cancel",
    ];

    let selection = Select::new()
        .with_prompt("Choose an option")
        .items(items)
        .default(0)
        .interact()
        .map_err(|_| ConfigCancelled)?;

    match selection {
        0 => Ok(ModifyChoice::Provider),
        1 => Ok(ModifyChoice::Key),
        2 => Ok(ModifyChoice::Language),
        3 => Ok(ModifyChoice::Everything),
        4 => Ok(ModifyChoice::Cancel),
        _ => Err(ConfigCancelled),
    }
}

// ============================================================================
// Wizard: provider → model → protocol → url → key
// ============================================================================

fn run_wizard(
    providers: &[crate::providers::Provider],
    current: &Option<crate::store::config_store::ProviderConfig>,
    mode: &str,
) -> Result<(), ConfigCancelled> {
    let mut step: usize = 0; // 0=provider, 1=protocol, 2=url, 3=key, 4=language, 5=done
    let mut provider: Option<&crate::providers::Provider> = None;
    let mut model: Option<&crate::providers::ModelInfo> = None;
    let mut protocol = String::from("openai");
    let mut url = String::new();
    let mut language = current
        .as_ref()
        .map(|c| c.language.clone())
        .unwrap_or_else(crate::store::config_store::detect_language);
    let mut api_key = if mode == "provider" {
        current
            .as_ref()
            .map(|c| c.api_key.clone())
            .unwrap_or_default()
    } else {
        String::new()
    };

    while step < 5 {
        match step {
            0 => {
                let result = pick_provider_and_model(providers, current)?;
                match result {
                    Some((p, m)) => {
                        provider = Some(p);
                        model = Some(m);
                        step = 1;
                    }
                    None => {
                        // Back: return to "what to modify" menu if we have a current config
                        if current.is_some() {
                            if let Some(ref c) = current {
                                show_current_config(c);
                            }
                            match ask_what_to_modify()? {
                                ModifyChoice::Cancel => return Err(ConfigCancelled),
                                ModifyChoice::Key => {
                                    // Use current provider name from config or fall back to first provider
                                    let provider_name = current
                                        .as_ref()
                                        .and_then(|c| c.get_provider())
                                        .map(|p| p.name.clone())
                                        .unwrap_or_else(|| providers[0].name.clone());
                                    let key = ask_api_key(&provider_name, current.as_ref())?;
                                    println!();
                                    let c = current.as_ref().unwrap();
                                    test_and_save(
                                        &c.provider,
                                        &c.model,
                                        &key,
                                        &c.protocol,
                                        &c.url,
                                        &c.language,
                                    )?;
                                    return Ok(());
                                }
                                ModifyChoice::Language => {
                                    let c = current.as_ref().unwrap();
                                    let new_lang = ask_language(&c.language)?;
                                    println!();
                                    save_config(
                                        &c.provider,
                                        &c.model,
                                        &c.api_key,
                                        &c.protocol,
                                        &c.url,
                                        &new_lang,
                                        &crate::paths::config_path(),
                                    )
                                    .map_err(|e| {
                                        eprintln!(
                                            "  {} Failed to save config: {}",
                                            console::style("Error:").red(),
                                            e
                                        );
                                        ConfigCancelled
                                    })?;
                                    println!();
                                    println!("{}", console::style("Language updated.").green());
                                    return Ok(());
                                }
                                ModifyChoice::Provider => {
                                    api_key = current
                                        .as_ref()
                                        .map(|c| c.api_key.clone())
                                        .unwrap_or_default();
                                    continue; // restart wizard
                                }
                                ModifyChoice::Everything => {
                                    api_key = String::new();
                                    continue; // restart wizard
                                }
                            }
                        }
                        continue;
                    }
                }
            }
            1 => {
                if let Some(p) = provider {
                    match pick_protocol(p, current.as_ref())? {
                        ProtocolChoice::Back => {
                            step = 0;
                            continue;
                        }
                        ProtocolChoice::Selected(proto) => {
                            protocol = proto;
                            step = 2;
                        }
                    }
                }
            }
            2 => {
                if let Some(p) = provider {
                    match ask_url(p, &protocol, current.as_ref())? {
                        UrlChoice::Back => {
                            step = 1;
                            continue;
                        }
                        UrlChoice::Selected(u) => {
                            url = u;
                            step = 3;
                        }
                    }
                }
            }
            3 => {
                if let Some(p) = provider {
                    api_key = ask_api_key(&p.name, current.as_ref())?;
                }
                if mode == "everything" {
                    step = 4; // continue to language step
                } else {
                    step = 5; // skip language, done
                }
            }
            4 => {
                language = ask_language(&language)?;
                step = 5;
            }
            _ => {}
        }
    }

    let p = provider.unwrap();
    let m = model.unwrap();
    println!();
    test_and_save(&p.id, &m.id, &api_key, &protocol, &url, &language)
}

// ============================================================================
// Step 0: Provider + Model selection
// ============================================================================

fn pick_provider_and_model<'a>(
    providers: &'a [crate::providers::Provider],
    current: &Option<crate::store::config_store::ProviderConfig>,
) -> Result<
    Option<(
        &'a crate::providers::Provider,
        &'a crate::providers::ModelInfo,
    )>,
    ConfigCancelled,
> {
    use dialoguer::Select;

    let current_provider_id = current.as_ref().map(|c| c.provider.as_str());

    loop {
        // --- Provider selection ---
        println!();
        println!("Select provider:");
        if let Some(c) = current {
            if let Some(p) = c.get_provider() {
                println!("  Current: {}", console::style(&p.name).dim());
            }
        }

        let mut provider_items: Vec<String> = providers
            .iter()
            .map(|p| {
                let marker = if Some(p.id.as_str()) == current_provider_id {
                    " (current)"
                } else {
                    ""
                };
                format!("{}  ({} models){}", p.name, p.models.len(), marker)
            })
            .collect();

        if current.is_some() {
            let mut items_with_back = vec!["Back".into()];
            items_with_back.append(&mut provider_items);
            provider_items = items_with_back;
        }

        let sel = Select::new()
            .with_prompt("Choose a provider")
            .items(&provider_items)
            .default(if current.is_some() { 1 } else { 0 })
            .interact()
            .map_err(|_| ConfigCancelled)?;

        let back_offset = if current.is_some() { 1 } else { 0 };

        if current.is_some() && sel == 0 {
            return Ok(None);
        }

        let provider = &providers[sel - back_offset];
        println!();

        // --- Model selection ---
        let current_model_id = current.as_ref().and_then(|c| {
            if c.provider == provider.id {
                Some(c.model.as_str())
            } else {
                None
            }
        });

        println!("Select model:");
        if let Some(mid) = current_model_id {
            let name = provider
                .models
                .iter()
                .find(|m| m.id == mid)
                .map(|m| m.name.as_str())
                .unwrap_or(mid);
            println!("  Current: {}", console::style(name).dim());
        }

        let mut model_items: Vec<String> = vec!["Back".into()];
        for m in &provider.models {
            let marker = if Some(m.id.as_str()) == current_model_id {
                " (current)"
            } else {
                ""
            };
            model_items.push(format!("{}{}", m.name, marker));
        }

        let model_sel = Select::new()
            .with_prompt("Choose a model")
            .items(&model_items)
            .default(1)
            .interact()
            .map_err(|_| ConfigCancelled)?;

        if model_sel == 0 {
            continue; // back to provider selection
        }

        let model = &provider.models[model_sel - 1];
        return Ok(Some((provider, model)));
    }
}

// ============================================================================
// Step 1: Protocol selection
// ============================================================================

enum ProtocolChoice {
    Back,
    Selected(String),
}

fn pick_protocol(
    provider: &crate::providers::Provider,
    current: Option<&crate::store::config_store::ProviderConfig>,
) -> Result<ProtocolChoice, ConfigCancelled> {
    use dialoguer::Select;

    let current_protocol = current.map(|c| c.protocol.as_str()).unwrap_or("openai");

    println!();
    if provider.protocols.len() == 1 {
        let proto = &provider.protocols[0];
        println!("Protocol: {} (only option)", console::style(proto).cyan());

        let items = &["Continue", "Back"];
        let sel = Select::new()
            .with_prompt("Choose")
            .items(items)
            .default(0)
            .interact()
            .map_err(|_| ConfigCancelled)?;

        if sel == 1 {
            return Ok(ProtocolChoice::Back);
        }
        return Ok(ProtocolChoice::Selected(proto.clone()));
    }

    println!("Select protocol:");
    println!("  Current: {}", console::style(current_protocol).dim());

    let mut items = vec!["Back".into()];
    for proto in &provider.protocols {
        let marker = if proto == current_protocol {
            " (current)"
        } else {
            ""
        };
        items.push(format!("{}{}", proto, marker));
    }

    let sel = Select::new()
        .with_prompt("Choose a protocol")
        .items(&items)
        .default(1)
        .interact()
        .map_err(|_| ConfigCancelled)?;

    if sel == 0 {
        return Ok(ProtocolChoice::Back);
    }

    let chosen = provider.protocols[sel - 1].clone();
    Ok(ProtocolChoice::Selected(chosen))
}

// ============================================================================
// Step 2: URL configuration
// ============================================================================

enum UrlChoice {
    Back,
    Selected(String),
}

fn ask_url(
    provider: &crate::providers::Provider,
    protocol: &str,
    current: Option<&crate::store::config_store::ProviderConfig>,
) -> Result<UrlChoice, ConfigCancelled> {
    let default_url = crate::providers::get_protocol_url(provider, protocol)
        .unwrap_or_else(|| "https://api.example.com/v1".into());
    let current_url_val = current
        .filter(|c| c.provider == provider.id)
        .map(|c| c.url.clone())
        .unwrap_or_else(|| default_url.clone());
    let current_url = current_url_val.as_str();

    println!();
    println!("Endpoint URL:");
    println!("  Default: {}", console::style(&default_url).dim());
    if current_url != default_url {
        println!("  Current: {}", console::style(current_url).dim());
    }
    println!("  (leave empty to keep current, '-' = reset to default, 'back' = previous step)");

    let input: String = dialoguer::Input::new()
        .with_prompt("URL")
        .default(current_url.to_string())
        .allow_empty(true)
        .interact_text()
        .map_err(|_| ConfigCancelled)?;

    let input = input.trim();
    if input == "back" {
        return Ok(UrlChoice::Back);
    }
    if input == "-" {
        println!(
            "  Reset to default ({})",
            console::style(&default_url).dim()
        );
        return Ok(UrlChoice::Selected(default_url));
    }
    if input.is_empty() {
        return Ok(UrlChoice::Selected(current_url.to_string()));
    }
    println!("  {}", console::style(input).green());
    Ok(UrlChoice::Selected(input.to_string()))
}

// ============================================================================
// Step 4: Summary language
// ============================================================================

fn ask_language(current_language: &str) -> Result<String, ConfigCancelled> {
    use dialoguer::Select;

    println!();
    println!("Summary language:");
    let current_label = if current_language == "zh" {
        "中文"
    } else {
        "English"
    };
    println!("  Current: {}", console::style(current_label).dim());

    let items = &["English", "中文", "Back"];
    let default_idx = if current_language == "zh" { 1 } else { 0 };

    let sel = Select::new()
        .with_prompt("Language")
        .items(items)
        .default(default_idx)
        .interact()
        .map_err(|_| ConfigCancelled)?;

    match sel {
        0 => Ok("en".into()),
        1 => Ok("zh".into()),
        2 => Ok(current_language.to_string()),
        _ => Err(ConfigCancelled),
    }
}

// ============================================================================
// Step 3: API key input (now step 3)
// ============================================================================

fn ask_api_key(
    _provider_name: &str,
    current: Option<&crate::store::config_store::ProviderConfig>,
) -> Result<String, ConfigCancelled> {
    println!();
    if let Some(c) = current {
        let masked = if c.api_key.len() > 4 {
            format!("***{}", &c.api_key[c.api_key.len() - 4..])
        } else {
            "(not set)".into()
        };
        println!("API key:");
        println!("  Current: {}", console::style(&masked).dim());
        println!("  (leave empty to keep current)");
    } else {
        println!("API key:");
    }

    let api_key =
        rpassword::prompt_password("API key (input hidden): ").map_err(|_| ConfigCancelled)?;

    let api_key = api_key.trim().to_string();
    if api_key.is_empty() {
        if let Some(c) = current {
            if !c.api_key.is_empty() {
                println!("  Keeping current API key.");
                return Ok(c.api_key.clone());
            }
        }
        println!("{}", console::style("API key cannot be empty.").red());
        return Err(ConfigCancelled);
    }
    println!("  API key received.");
    Ok(api_key)
}

// ============================================================================
// Test connection and save
// ============================================================================

fn test_and_save(
    provider_id: &str,
    model_id: &str,
    api_key: &str,
    protocol: &str,
    url: &str,
    language: &str,
) -> Result<(), ConfigCancelled> {
    use crate::store::config_store::{save_config, ProviderConfig};
    use dialoguer::Confirm;

    let provider = crate::providers::get_provider(provider_id).ok_or(ConfigCancelled)?;

    println!();
    println!("Testing connection to {}...", provider.name);

    // Build a test config and try the connection
    let test_config = ProviderConfig {
        provider: provider_id.into(),
        model: model_id.into(),
        api_key: api_key.into(),
        api_key_source: None,
        protocol: protocol.into(),
        url: url.into(),
        language: language.into(),
    };

    match crate::llm::get_client(&test_config, None) {
        Ok(client) => match client.test_connection() {
            Ok(response) => {
                println!(
                    "  {} {}",
                    console::style("Connection OK:").green(),
                    response.trim()
                );
            }
            Err(e) => {
                println!(
                    "  {} test request failed: {}",
                    console::style("Warning:").yellow(),
                    e
                );
                let confirmed = Confirm::new()
                    .with_prompt("Save config anyway?")
                    .default(false)
                    .interact()
                    .map_err(|_| ConfigCancelled)?;
                if !confirmed {
                    return Err(ConfigCancelled);
                }
            }
        },
        Err(e) => {
            println!(
                "  {} cannot create client: {}",
                console::style("Warning:").yellow(),
                e
            );
            let confirmed = Confirm::new()
                .with_prompt("Save config anyway?")
                .default(false)
                .interact()
                .map_err(|_| ConfigCancelled)?;
            if !confirmed {
                return Err(ConfigCancelled);
            }
        }
    }

    let config_path = crate::paths::config_path();
    save_config(
        provider_id,
        model_id,
        api_key,
        protocol,
        url,
        language,
        &config_path,
    )
    .map_err(|e| {
        eprintln!(
            "  {} Failed to save config: {}",
            console::style("Error:").red(),
            e
        );
        ConfigCancelled
    })?;

    println!();
    println!(
        "{}",
        console::style(format!("Config saved to {}", config_path.display())).green()
    );
    Ok(())
}

// ============================================================================
// path and test commands
// ============================================================================

pub fn path(args: JsonFlag) -> Result<(), String> {
    let p = crate::paths::config_path();
    if args.json() {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("path".into(), p.to_string_lossy().to_string().into());
        super::output::print_json_success(extra);
    } else {
        println!("  {} {}", super::output::label("Config path:"), p.display());
    }
    Ok(())
}

pub fn test(args: JsonFlag) -> Result<(), String> {
    let json_output = args.json();
    let config = crate::store::config_store::load_config(&crate::paths::config_path());

    let config = match config {
        Some(c) if c.is_ready() => c,
        _ => {
            super::output::exit_with_error(
                "No LLM provider configured. Run `frais config manage`.",
                json_output,
                2,
                "config_missing",
                "Run `frais config manage` to configure an LLM provider.",
                BTreeMap::<String, serde_json::Value>::new(),
            );
        }
    };

    let client = match crate::llm::get_client(&config, None) {
        Ok(c) => c,
        Err(e) => {
            super::output::exit_with_error(
                &e,
                json_output,
                2,
                "config_missing",
                "Check your provider configuration.",
                BTreeMap::<String, serde_json::Value>::new(),
            );
        }
    };

    match client.test_connection() {
        Ok(response) => {
            if json_output {
                let provider_name = crate::providers::get_provider(&config.provider)
                    .map(|p| p.name)
                    .unwrap_or_else(|| config.provider.clone());
                let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
                extra.insert("provider".into(), provider_name.into());
                extra.insert("model".into(), config.model.into());
                extra.insert("url".into(), config.url.into());
                extra.insert("response".into(), response.into());
                super::output::print_json_success(extra);
            } else {
                let provider_name = crate::providers::get_provider(&config.provider)
                    .map(|p| p.name)
                    .unwrap_or_else(|| config.provider.clone());
                println!("  {} {}", super::output::label("Provider:"), provider_name);
                println!("  {} {}", super::output::label("Model:"), config.model);
                println!("  {} {}", super::output::label("URL:"), config.url);
                println!(
                    "  {} {}",
                    super::output::label("Response:"),
                    super::output::success(response.trim())
                );
            }
        }
        Err(e) => {
            super::output::exit_with_error(
                &format!("Connection failed: {e}"),
                json_output,
                2,
                "connection_error",
                "Check your API key and network connection, then try again.",
                BTreeMap::<String, serde_json::Value>::new(),
            );
        }
    }

    Ok(())
}
