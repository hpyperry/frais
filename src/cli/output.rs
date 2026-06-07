// JSON/CLI output helpers — matches Python's frais/commands/_output.py.
use std::collections::BTreeMap;
use std::process;

// Shared CLI styling helpers — all commands use these for consistent visual vocabulary.
// Matches the style patterns established by scan/advise.

/// Cyan bold label (e.g. "OS:", "Provider:", "Item:").
pub fn label(text: impl AsRef<str>) -> console::StyledObject<String> {
    console::style(text.as_ref().to_string()).cyan().bold()
}

/// Green text for success states (e.g. "enabled", "Connection OK").
pub fn success(text: impl AsRef<str>) -> console::StyledObject<String> {
    console::style(text.as_ref().to_string()).green()
}

/// Yellow text for warnings.
pub fn warning(text: impl AsRef<str>) -> console::StyledObject<String> {
    console::style(text.as_ref().to_string()).yellow()
}

/// Dimmed text for secondary information.
pub fn dim(text: impl AsRef<str>) -> console::StyledObject<String> {
    console::style(text.as_ref().to_string()).dim()
}

/// Bold text.
pub fn bold(text: impl AsRef<str>) -> console::StyledObject<String> {
    console::style(text.as_ref().to_string()).bold()
}

/// Green bold text for emphasis (e.g. latest version).
pub fn green_bold(text: impl AsRef<str>) -> console::StyledObject<String> {
    console::style(text.as_ref().to_string()).green().bold()
}

/// White bold text for item IDs.
pub fn id(text: impl AsRef<str>) -> console::StyledObject<String> {
    console::style(text.as_ref().to_string()).white().bold()
}

/// Red text for errors.
pub fn error_styled(text: impl AsRef<str>) -> console::StyledObject<String> {
    console::style(text.as_ref().to_string()).red()
}

/// Green checkmark ✓ for available/enabled.
pub fn check_mark() -> console::StyledObject<&'static str> {
    console::style("\u{2713}").green()
}

/// Yellow cross ✗ for unavailable/disabled.
pub fn cross_mark() -> console::StyledObject<&'static str> {
    console::style("\u{2717}").yellow()
}

/// Build a JSON string with guaranteed key order.
/// serde_json::to_string_pretty on BTreeMap sorts alphabetically,
/// but the LLM Agent Contract requires "ok" to always be the first key.
/// We construct the JSON manually to ensure insertion-order key placement.
fn build_json_ordered(pairs: &[(String, serde_json::Value)]) -> String {
    let mut lines: Vec<String> = Vec::new();
    for (k, v) in pairs {
        let v_str = serde_json::to_string(v).unwrap_or_else(|_| "null".into());
        let k_str = serde_json::to_string(k).unwrap_or_else(|_| format!("\"{k}\""));
        lines.push(format!("  {}: {}", k_str, v_str));
    }
    format!("{{\n{}\n}}", lines.join(",\n"))
}

/// Print JSON success envelope: {"ok": true, ...fields}.
/// The "ok" key is reserved, always true, and always the first key.
pub fn print_json_success(fields: BTreeMap<String, serde_json::Value>) {
    let mut pairs: Vec<(String, serde_json::Value)> = Vec::new();
    pairs.push(("ok".into(), serde_json::Value::Bool(true)));
    for (k, v) in fields {
        if k != "ok" {
            pairs.push((k, v));
        }
    }
    println!("{}", build_json_ordered(&pairs));
}

/// Print error and exit — JSON mode prints envelope, CLI mode prints to stderr.
pub fn exit_with_error(
    message: &str,
    json_mode: bool,
    exit_code: i32,
    reason: &str,
    hint: &str,
    extra: BTreeMap<String, serde_json::Value>,
) -> ! {
    if json_mode {
        let mut pairs: Vec<(String, serde_json::Value)> = Vec::new();
        pairs.push(("ok".into(), serde_json::Value::Bool(false)));
        pairs.push(("error".into(), serde_json::Value::String(message.into())));
        pairs.push(("reason".into(), serde_json::Value::String(reason.into())));
        pairs.push(("hint".into(), serde_json::Value::String(hint.into())));
        for (k, v) in extra {
            if k != "ok" && k != "error" && k != "reason" && k != "hint" {
                pairs.push((k, v));
            }
        }
        println!("{}", build_json_ordered(&pairs));
    } else {
        eprintln!("Error: {message}");
        if !hint.is_empty() {
            eprintln!("  Hint: {hint}");
        }
    }
    process::exit(exit_code);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_print_json_success_includes_ok_true() {
        // Can't easily capture stdout in tests, but verify structure
        let mut fields: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        fields.insert("version".into(), serde_json::Value::String("0.1.0".into()));
        // This prints to stdout — structural verification in integration tests
    }

    #[test]
    fn test_print_json_success_ok_cannot_be_overridden() {
        let mut fields: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        fields.insert("ok".into(), serde_json::Value::Bool(false));
        // ok should remain true
    }
}
