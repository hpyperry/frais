// Ignore filter — matches Python's frais/ignore_filter.py.

use crate::models::ScanResult;
use crate::store::ignore_store;

/// Result of applying the ignore filter.
pub struct IgnoreFilterResult {
    pub scan_result: ScanResult,
    pub ignored_count: usize,
}

/// Filter out ignored items and their candidates from a scan result.
pub fn apply_ignore_filter(scan_result: &ScanResult) -> IgnoreFilterResult {
    let ignored_ids = ignore_store::load_ignored(&crate::paths::ignore_path());

    if ignored_ids.is_empty() {
        return IgnoreFilterResult {
            scan_result: scan_result.clone(),
            ignored_count: 0,
        };
    }

    let mut filtered_result = scan_result.clone();
    let mut ignored_count = 0;

    for plugin_result in filtered_result.plugin_results.values_mut() {
        // Filter items (Python: plugin_result.items = [item for item in ... if item.id not in ignored_ids])
        plugin_result.items.retain(|item| !ignored_ids.contains(&item.id));

        // Filter candidates and count removed — matches Python's ignored_count logic
        let before_count = plugin_result.candidates.len();
        plugin_result.candidates.retain(|c| !ignored_ids.contains(&c.item.id));
        ignored_count += before_count - plugin_result.candidates.len();
    }

    IgnoreFilterResult {
        scan_result: filtered_result,
        ignored_count,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::SystemProfile;
    use std::collections::BTreeMap;

    #[test]
    fn test_apply_ignore_filter_with_empty_list() {
        let sr = ScanResult {
            system: SystemProfile {
                os_name: "macOS".into(),
                os_version: "15.0".into(),
                arch: "arm64".into(),
                applications_paths: vec![],
            },
            plugin_results: BTreeMap::new(),
        };
        let result = apply_ignore_filter(&sr);
        assert_eq!(result.ignored_count, 0);
    }
}
