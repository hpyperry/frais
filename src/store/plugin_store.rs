// Plugin state store — matches Python's frais/store/plugin_store.py.
// Reads/writes ~/.frais/config/plugins.toml.

use std::collections::BTreeMap;
use std::path::Path;

/// Load plugin enabled/disabled state.
/// Returns empty map if file doesn't exist or can't be parsed.
pub fn load_plugins_config(path: &Path) -> BTreeMap<String, bool> {
    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return BTreeMap::new(),
    };

    let toml_value: toml::Value = match toml::from_str(&content) {
        Ok(v) => v,
        Err(e) => {
            log::warn!("plugin store TOML parse error, returning empty: {}", e);
            return BTreeMap::new();
        }
    };

    let mut result = BTreeMap::new();
    if let Some(plugins) = toml_value.get("plugins").and_then(|v| v.as_table()) {
        for (name, value) in plugins {
            if let Some(enabled) = value.as_bool() {
                result.insert(name.clone(), enabled);
            }
        }
    }
    result
}

/// Initialize the plugins config file with defaults from all discovered plugins.
/// Only writes if the file does not already exist — matches Python's idempotent init.
pub fn init_plugins_config(
    path: &Path,
    plugins: &BTreeMap<String, bool>,
) -> Result<(), String> {
    if path.exists() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("Cannot create config dir: {e}"))?;
    }
    _write_plugins_config(plugins, path)
}

/// Save a single plugin's state.
pub fn save_plugin_state(
    name: &str,
    enabled: bool,
    path: &Path,
) -> Result<(), String> {
    let mut config = load_plugins_config(path);
    config.insert(name.to_string(), enabled);
    _write_plugins_config(&config, path)
}

/// Remove a plugin from the config.
pub fn remove_plugin_state(name: &str, path: &Path) -> Result<bool, String> {
    let mut config = load_plugins_config(path);
    let removed = config.remove(name).is_some();
    _write_plugins_config(&config, path)?;
    Ok(removed)
}

/// Build TOML content with sorted keys and proper escaping.
fn _write_plugins_config(config: &BTreeMap<String, bool>, path: &Path) -> Result<(), String> {
    // Build TOML content with sorted keys
    let mut plugins_section = String::from("[plugins]\n");
    let mut sorted: Vec<_> = config.iter().collect();
    sorted.sort_by(|a, b| a.0.cmp(b.0));
    for (name, enabled) in &sorted {
        // Always wrap plugin names in quoted keys to handle names with
        // spaces, dots, or digits — matches TOML quoted key spec.
        plugins_section.push_str(&format!(
            "\"{}\" = {}\n",
            name.replace('\\', "\\\\").replace('"', "\\\""),
            enabled
        ));
    }

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("Cannot create config dir: {e}"))?;
    }

    let tmp_path = path.with_extension("toml.tmp");
    std::fs::write(&tmp_path, &plugins_section)
        .map_err(|e| format!("Cannot write plugins config: {e}"))?;
    std::fs::rename(&tmp_path, path)
        .map_err(|e| format!("Cannot save plugins config: {e}"))?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_load_plugins_config_empty_when_no_file() {
        let config = load_plugins_config(Path::new("/nonexistent/plugins.toml"));
        assert!(config.is_empty());
    }

    #[test]
    fn test_load_plugins_config_reads_toml() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("plugins.toml");
        std::fs::write(
            &path,
            "[plugins]\napplications = true\nhomebrew = false\n",
        )
        .unwrap();

        let config = load_plugins_config(&path);
        assert_eq!(config.get("applications"), Some(&true));
        assert_eq!(config.get("homebrew"), Some(&false));
    }

    #[test]
    fn test_save_plugin_state_creates_file() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("plugins.toml");

        save_plugin_state("homebrew", false, &path).unwrap();
        let config = load_plugins_config(&path);
        assert_eq!(config.get("homebrew"), Some(&false));
    }

    #[test]
    fn test_save_plugin_state_overwrites_existing() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("plugins.toml");

        save_plugin_state("npm", true, &path).unwrap();
        save_plugin_state("npm", false, &path).unwrap();
        let config = load_plugins_config(&path);
        assert_eq!(config.get("npm"), Some(&false));
    }

    #[test]
    fn test_remove_plugin_state_existing() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("plugins.toml");

        save_plugin_state("homebrew", true, &path).unwrap();
        let removed = remove_plugin_state("homebrew", &path).unwrap();
        assert!(removed);
        let config = load_plugins_config(&path);
        assert!(!config.contains_key("homebrew"));
    }

    #[test]
    fn test_remove_plugin_state_not_found() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("plugins.toml");

        let removed = remove_plugin_state("nonexistent", &path).unwrap();
        assert!(!removed);
    }
}
