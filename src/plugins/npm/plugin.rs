// NpmPlugin — matches Python's frais/plugins/npm/plugin.py.
use crate::models::{
    DependencyImpact, PluginScanResult, SoftwareItem, SourceKind, SystemProfile, UpdateCandidate,
};
use crate::plugins::subprocess_json::run_json;
use crate::plugins::ScannerPlugin;
use std::collections::BTreeMap;

pub struct NpmPlugin;

impl ScannerPlugin for NpmPlugin {
    fn name(&self) -> &'static str {
        "npm"
    }
    fn enabled_by_default(&self) -> bool {
        true
    }
    fn display_color(&self) -> &'static str {
        "bright_magenta"
    }
    fn scan_steps(&self) -> &'static [&'static str] {
        &["checking outdated packages"]
    }
    fn is_available(&self) -> bool {
        let path = which::which("npm").ok();
        log::debug!("npm which npm={:?}", path);
        path.is_some()
    }

    fn scan(
        &self,
        _system: &SystemProfile,
        on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
        _max_workers: usize,
    ) -> PluginScanResult {
        if !self.is_available() {
            log::info!("npm unavailable");
            return PluginScanResult {
                items: vec![],
                candidates: vec![],
                skipped: vec!["npm is not installed or `npm` is not on PATH.".into()],
            };
        }

        log::info!("npm scan outdated start");
        // npm outdated -g --json exits with code 1 when there are outdated packages
        let raw = match run_json(&["npm", "outdated", "-g", "--json"], &[0, 1], 60) {
            Ok(data) => data,
            Err(e) => {
                log::warn!("npm outdated failed error={}", e);
                return PluginScanResult {
                    items: vec![],
                    candidates: vec![],
                    skipped: vec![e],
                };
            }
        };

        if raw.as_object().map(|o| o.is_empty()).unwrap_or(true) {
            log::info!("npm no outdated packages");
            return PluginScanResult::default();
        }

        let (candidates, items) = parse_outdated(&raw);
        log::info!("npm outdated items={}", items.len());
        if let Some(cb) = on_progress {
            cb(0, items.len(), items.len());
        }
        PluginScanResult {
            items,
            candidates,
            skipped: vec![],
        }
    }

    /// scan_all — matches Python: runs npm ls + npm outdated, then merges.
    fn scan_all(
        &self,
        _system: &SystemProfile,
        on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
        _max_workers: usize,
    ) -> PluginScanResult {
        if !self.is_available() {
            log::info!("npm unavailable");
            return PluginScanResult {
                items: vec![],
                candidates: vec![],
                skipped: vec!["npm is not installed or `npm` is not on PATH.".into()],
            };
        }

        log::info!("npm scan all start");
        let installed_raw = match run_json(&["npm", "ls", "-g", "--depth=0", "--json"], &[0], 60) {
            Ok(data) => data,
            Err(e) => {
                log::warn!("npm scan all failed error={}", e);
                return PluginScanResult {
                    items: vec![],
                    candidates: vec![],
                    skipped: vec![e],
                };
            }
        };
        let outdated_raw = match run_json(&["npm", "outdated", "-g", "--json"], &[0, 1], 60) {
            Ok(data) => data,
            Err(e) => {
                log::warn!("npm scan all failed error={}", e);
                return PluginScanResult {
                    items: vec![],
                    candidates: vec![],
                    skipped: vec![e],
                };
            }
        };

        let (candidates, _) = parse_outdated(&outdated_raw);
        let all_items = parse_installed(&installed_raw);
        log::info!(
            "npm scan all items={} outdated={}",
            all_items.len(),
            candidates.len()
        );
        if let Some(cb) = on_progress {
            cb(0, all_items.len(), all_items.len());
        }
        PluginScanResult {
            items: all_items,
            candidates,
            skipped: vec![],
        }
    }
}

// ============================================================================
// Parse outdated output
// ============================================================================

/// Parse npm outdated -g --json output into candidates and items.
/// Matches Python's _parse_outdated().
fn parse_outdated(data: &serde_json::Value) -> (Vec<UpdateCandidate>, Vec<SoftwareItem>) {
    let mut candidates = Vec::new();
    let mut items = Vec::new();

    let packages = match data.as_object() {
        Some(obj) => obj,
        None => return (candidates, items),
    };

    for (name, info) in packages {
        let cand = make_candidate(name, info);
        candidates.push(cand.clone());
        items.push(cand.item);
    }

    // Sort for determinism
    candidates.sort_by(|a, b| a.item.id.cmp(&b.item.id));
    items.sort_by(|a, b| a.id.cmp(&b.id));

    (candidates, items)
}

/// Parse npm ls -g --depth=0 --json output into items.
/// Matches Python's _parse_installed().
fn parse_installed(data: &serde_json::Value) -> Vec<SoftwareItem> {
    let deps = match data.get("dependencies").and_then(|v| v.as_object()) {
        Some(d) => d,
        None => return vec![],
    };

    let mut items: Vec<SoftwareItem> = Vec::new();
    for (name, info) in deps {
        let version = info
            .get("version")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        items.push(SoftwareItem {
            id: format!("npm:{}", name),
            name: name.clone(),
            kind: "package".into(),
            source: SourceKind::NpmGlobal,
            current_version: version,
            path: None,
            metadata: BTreeMap::new(),
        });
    }

    items.sort_by(|a, b| a.id.cmp(&b.id));
    items
}

// ============================================================================
// Candidate construction — matches Python's _make_candidate()
// ============================================================================

fn make_candidate(name: &str, info: &serde_json::Value) -> UpdateCandidate {
    let current = info
        .get("current")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let latest = info
        .get("latest")
        .or_else(|| info.get("wanted"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    log::debug!(
        "npm candidate name={} current={} latest={}",
        name,
        current.as_deref().unwrap_or("unknown"),
        latest.as_deref().unwrap_or("unknown")
    );

    let item = SoftwareItem {
        id: format!("npm:{}", name),
        name: name.to_string(),
        kind: "package".into(),
        source: SourceKind::NpmGlobal,
        current_version: current,
        path: None,
        metadata: BTreeMap::new(),
    };

    UpdateCandidate {
        item,
        latest_version: latest,
        release_notes: None,
        dependency_impact: DependencyImpact {
            used_by: vec![],
            depends_on: vec![],
            impact_level: "low".into(),
        },
        risk_level: None,
        ai_summary: None,
        recommended_action: None,
        can_auto_update: true,
        command: vec![
            "npm".into(),
            "install".into(),
            "-g".into(),
            name.to_string(),
        ],
        evidence: vec![format!("https://www.npmjs.com/package/{}", name)],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_available_checks_npm() {
        let plugin = NpmPlugin;
        let _ = plugin.is_available();
    }

    #[test]
    fn test_parse_outdated_empty() {
        let data = serde_json::json!({});
        let (candidates, items) = parse_outdated(&data);
        assert!(items.is_empty());
        assert!(candidates.is_empty());
    }

    #[test]
    fn test_plugin_name() {
        assert_eq!(NpmPlugin.name(), "npm");
    }

    #[test]
    fn test_candidate_kind_package() {
        let info = serde_json::json!({
            "current": "1.0.0",
            "latest": "2.0.0"
        });
        let cand = make_candidate("test-pkg", &info);
        assert_eq!(cand.item.kind, "package");
        assert_eq!(cand.item.source, SourceKind::NpmGlobal);
        assert!(!cand.evidence.is_empty());
        assert!(cand.evidence[0].contains("npmjs.com"));
    }
}
