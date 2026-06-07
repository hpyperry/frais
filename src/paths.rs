// Path constants — matches Python's frais/paths.py.
// All paths are under ~/.frais/

use std::path::PathBuf;

/// Base directory for all Frais data.
pub fn frais_home() -> PathBuf {
    dirs_frais_home()
}

fn dirs_frais_home() -> PathBuf {
    let home = std::env::var("FRAIS_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            let mut p = dirs_home();
            p.push(".frais");
            p
        });
    home
}

fn dirs_home() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/tmp"))
}

/// Default log directory: ~/.frais/log
pub fn default_log_dir() -> PathBuf {
    let mut p = frais_home();
    p.push("log");
    p
}

/// Default log file: ~/.frais/log/frais.log
pub fn default_log_file() -> PathBuf {
    let mut p = default_log_dir();
    p.push("frais.log");
    p
}

/// Default error log file: ~/.frais/log/error.log
pub fn default_error_log_file() -> PathBuf {
    let mut p = default_log_dir();
    p.push("error.log");
    p
}

/// Scan cache file: ~/.frais/log/last_advice.json
pub fn advice_cache() -> PathBuf {
    let mut p = default_log_dir();
    p.push("last_advice.json");
    p
}

/// Config directory: ~/.frais/config
pub fn config_dir() -> PathBuf {
    let mut p = frais_home();
    p.push("config");
    p
}

/// Config file: ~/.frais/config/config.toml
pub fn config_path() -> PathBuf {
    let mut p = config_dir();
    p.push("config.toml");
    p
}

/// Plugin state file: ~/.frais/config/plugins.toml
pub fn plugins_config_path() -> PathBuf {
    let mut p = config_dir();
    p.push("plugins.toml");
    p
}

/// Ignore list file: ~/.frais/config/ignore.txt
pub fn ignore_path() -> PathBuf {
    let mut p = config_dir();
    p.push("ignore.txt");
    p
}

/// Max log file size before rotation: 50 MB (matches Python's LOG_MAX_SIZE)
pub const LOG_MAX_SIZE: u64 = 50 * 1024 * 1024;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_frais_home_from_env() {
        std::env::set_var("FRAIS_HOME", "/tmp/test_frais_home");
        let home = frais_home();
        assert_eq!(home, PathBuf::from("/tmp/test_frais_home"));
        std::env::remove_var("FRAIS_HOME");
    }

    #[test]
    fn test_path_constants_are_absolute() {
        let cache = advice_cache();
        assert!(cache.is_absolute() || cache.starts_with("/"));
    }

    #[test]
    fn test_config_path_ends_with_config_toml() {
        let p = config_path();
        assert!(p.ends_with("config.toml"));
    }
}
