// Scan cache store — matches Python's frais/store/scan_cache.py.
// Writes scan results to ~/.frais/cache/last_advice.json atomically.

use crate::models::ScanResult;
use std::path::Path;

/// Save a scan result to the cache file atomically.
pub fn save_scan_cache(scan_result: &ScanResult, path: &Path) -> Result<(), String> {
    let json = serde_json::to_string_pretty(scan_result)
        .map_err(|e| format!("Cannot serialize scan result: {e}"))?;

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("Cannot create cache dir: {e}"))?;
    }

    // Atomic write: write to .tmp then rename
    let tmp_path = path.with_extension("json.tmp");
    std::fs::write(&tmp_path, &json).map_err(|e| format!("Cannot write cache: {e}"))?;
    std::fs::rename(&tmp_path, path).map_err(|e| format!("Cannot save cache: {e}"))?;

    log::info!("Scan cache saved to {}", path.display());
    Ok(())
}

/// Load a scan result from the cache file.
pub fn load_scan_cache(path: &Path) -> Result<ScanResult, String> {
    let json = std::fs::read_to_string(path).map_err(|e| format!("Cannot read cache: {e}"))?;
    let result: ScanResult =
        serde_json::from_str(&json).map_err(|e| format!("Cannot parse cache: {e}"))?;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::SystemProfile;
    use std::collections::BTreeMap;

    #[test]
    fn test_save_and_load_cache_round_trip() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("cache.json");

        let sr = ScanResult {
            system: SystemProfile {
                os_name: "macOS".into(),
                os_version: "15.0".into(),
                arch: "arm64".into(),
                applications_paths: vec!["/Applications".into()],
            },
            plugin_results: BTreeMap::new(),
        };

        save_scan_cache(&sr, &path).unwrap();
        let loaded = load_scan_cache(&path).unwrap();
        assert_eq!(loaded.system.os_name, "macOS");
    }

    #[test]
    fn test_save_cache_creates_parent_dirs() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("subdir").join("cache.json");

        let sr = ScanResult {
            system: SystemProfile {
                os_name: "macOS".into(),
                os_version: "15.0".into(),
                arch: "arm64".into(),
                applications_paths: vec![],
            },
            plugin_results: BTreeMap::new(),
        };

        assert!(save_scan_cache(&sr, &path).is_ok());
        assert!(path.exists());
    }
}
