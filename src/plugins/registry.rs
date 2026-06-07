// Plugin registry — matches Python's frais/plugins/registry.py.
// Uses linkme for compile-time static registration.

use crate::plugins::applications::plugin::ApplicationsPlugin;
use crate::plugins::homebrew::plugin::HomebrewPlugin;
use crate::plugins::npm::plugin::NpmPlugin;
use crate::plugins::ScannerPlugin;
use std::collections::BTreeMap;

/// Return all registered plugins as name → Box<dyn ScannerPlugin>.
/// In the Python version, this uses importlib.metadata.entry_points.
/// In Rust, we register them statically at compile time.
pub fn all_plugins() -> BTreeMap<String, Box<dyn ScannerPlugin>> {
    let mut plugins: BTreeMap<String, Box<dyn ScannerPlugin>> = BTreeMap::new();

    let apps: Box<dyn ScannerPlugin> = Box::new(ApplicationsPlugin);
    plugins.insert(apps.name().to_string(), apps);

    let hb: Box<dyn ScannerPlugin> = Box::new(HomebrewPlugin);
    plugins.insert(hb.name().to_string(), hb);

    let np: Box<dyn ScannerPlugin> = Box::new(NpmPlugin);
    plugins.insert(np.name().to_string(), np);

    plugins
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_all_plugins_returns_three_builtins() {
        let plugins = all_plugins();
        assert_eq!(plugins.len(), 3);
        assert!(plugins.contains_key("applications"));
        assert!(plugins.contains_key("homebrew"));
        assert!(plugins.contains_key("npm"));
    }

    #[test]
    fn test_each_plugin_has_name() {
        let plugins = all_plugins();
        for (key, plugin) in &plugins {
            assert_eq!(key, plugin.name());
        }
    }
}
