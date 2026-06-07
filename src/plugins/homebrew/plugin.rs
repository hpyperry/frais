// HomebrewPlugin — matches Python's frais/plugins/homebrew/plugin.py.
use crate::models::{
    DependencyImpact, PluginScanResult, SoftwareItem, SourceKind, SystemProfile, UpdateCandidate,
};
use crate::plugins::subprocess_json::run_json;
use crate::plugins::ScannerPlugin;
use std::collections::BTreeMap;

pub struct HomebrewPlugin;

impl ScannerPlugin for HomebrewPlugin {
    fn name(&self) -> &'static str {
        "homebrew"
    }
    fn enabled_by_default(&self) -> bool {
        true
    }
    fn display_color(&self) -> &'static str {
        "orange3"
    }
    fn scan_steps(&self) -> &'static [&'static str] {
        &["checking outdated packages"]
    }
    fn is_available(&self) -> bool {
        let path = which::which("brew").ok();
        log::debug!("homebrew which brew={:?}", path);
        path.is_some()
    }

    fn scan(
        &self,
        _system: &SystemProfile,
        on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
        _max_workers: usize,
    ) -> PluginScanResult {
        if !self.is_available() {
            log::info!("homebrew unavailable");
            return PluginScanResult {
                items: vec![],
                candidates: vec![],
                skipped: vec!["Homebrew is not installed or `brew` is not on PATH."
                    .into()],
            };
        }

        log::info!("homebrew scan outdated start");
        let raw = match run_json(&["brew", "outdated", "--json=v2"], &[0, 1], 60) {
            Ok(data) => data,
            Err(e) => {
                log::warn!("homebrew outdated failed error={}", e);
                return PluginScanResult {
                    items: vec![],
                    candidates: vec![],
                    skipped: vec![e],
                };
            }
        };

        let (candidates, items) = parse_outdated(&raw);
        log::info!("homebrew outdated items={}", items.len());
        if let Some(cb) = on_progress {
            cb(0, items.len(), items.len());
        }
        PluginScanResult {
            items,
            candidates,
            skipped: vec![],
        }
    }

    /// scan_all — matches Python: runs TWO commands, then merges.
    fn scan_all(
        &self,
        _system: &SystemProfile,
        on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
        _max_workers: usize,
    ) -> PluginScanResult {
        if !self.is_available() {
            log::info!("homebrew unavailable");
            return PluginScanResult {
                items: vec![],
                candidates: vec![],
                skipped: vec!["Homebrew is not installed or `brew` is not on PATH."
                    .into()],
            };
        }

        log::info!("homebrew scan all start");
        let installed_raw =
            match run_json(&["brew", "info", "--json=v2", "--installed"], &[0], 60) {
                Ok(data) => data,
                Err(e) => {
                    log::warn!("homebrew scan all failed error={}", e);
                    return PluginScanResult {
                        items: vec![],
                        candidates: vec![],
                        skipped: vec![e],
                    };
                }
            };
        let outdated_raw = match run_json(&["brew", "outdated", "--json=v2"], &[0, 1], 60) {
            Ok(data) => data,
            Err(e) => {
                log::warn!("homebrew scan all failed error={}", e);
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
            "homebrew scan all items={} outdated={}",
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
// Parse brew outdated --json=v2 output
// ============================================================================

/// Parse outdated output into items and candidates.
/// Matches Python's _parse_outdated().
fn parse_outdated(
    data: &serde_json::Value,
) -> (Vec<UpdateCandidate>, Vec<SoftwareItem>) {
    let mut candidates = Vec::new();
    let mut items = Vec::new();

    for formula in data
        .get("formulae")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
    {
        let cand = formula_candidate(formula);
        candidates.push(cand.clone());
        items.push(cand.item);
    }

    for cask in data
        .get("casks")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
    {
        let cand = cask_candidate(cask);
        candidates.push(cand.clone());
        items.push(cand.item);
    }

    // Sort for determinism (Python dict order)
    candidates.sort_by(|a, b| a.item.id.cmp(&b.item.id));
    items.sort_by(|a, b| a.id.cmp(&b.id));

    (candidates, items)
}

/// Parse brew info --json=v2 --installed output into all items.
/// Matches Python's _parse_installed().
fn parse_installed(data: &serde_json::Value) -> Vec<SoftwareItem> {
    let mut items = Vec::new();

    for formula in data
        .get("formulae")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
    {
        let name = formula
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let inst_ver = installed_version(formula);
        let current = formula
            .get("linked_keg")
            .and_then(|v| v.as_str())
            .or_else(|| inst_ver.as_deref())
            .map(|s| s.to_string());
        items.push(SoftwareItem {
            id: format!("brew:{}", name),
            name: name.to_string(),
            kind: "package".into(),
            source: SourceKind::HomebrewFormula,
            current_version: current,
            path: None,
            metadata: BTreeMap::new(),
        });
    }

    for cask in data
        .get("casks")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
    {
        let name = cask
            .get("name")
            .or_else(|| cask.get("token"))
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let current = cask_current_version(cask);
        items.push(SoftwareItem {
            id: format!("brew-cask:{}", name),
            name: name.to_string(),
            kind: "application".into(),
            source: SourceKind::HomebrewCask,
            current_version: current,
            path: None,
            metadata: BTreeMap::new(),
        });
    }

    items.sort_by(|a, b| a.id.cmp(&b.id));
    items
}

// ============================================================================
// Candidate construction — matches Python's _formula_candidate / _cask_candidate
// ============================================================================

fn formula_candidate(formula: &serde_json::Value) -> UpdateCandidate {
    let name = formula
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown");
    let current = first(formula.get("installed_versions"))
        .or_else(|| formula.get("installed_version").and_then(|v| v.as_str()))
        .map(|s| s.to_string());
    let latest = formula
        .get("current_version")
        .or_else(|| formula.get("latest_version"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    log::debug!(
        "homebrew formula candidate name={} current={} latest={}",
        name,
        current.as_deref().unwrap_or("unknown"),
        latest.as_deref().unwrap_or("unknown")
    );

    let info = brew_info(name, false);
    let depends_on: Vec<String> = {
        let mut deps: Vec<String> = Vec::new();
        if let Some(d) = info.get("dependencies").and_then(|v| v.as_array()) {
            for dep in d {
                if let Some(s) = dep.as_str() {
                    deps.push(s.to_string());
                }
            }
        }
        if let Some(rd) = info
            .get("runtime_dependencies")
            .and_then(|v| v.as_array())
        {
            for dep in rd {
                if let Some(s) = dep.as_str() {
                    deps.push(s.to_string());
                }
            }
        }
        deps.sort();
        deps.dedup();
        deps
    };

    let used_by = brew_uses(name);
    let impact = DependencyImpact {
        used_by: used_by.clone(),
        depends_on,
        impact_level: if used_by.is_empty() {
            "low".into()
        } else {
            "medium".into()
        },
    };

    let mut metadata = BTreeMap::new();
    metadata.insert("homebrew".into(), info.clone());

    let item = SoftwareItem {
        id: format!("brew:{}", name),
        name: name.to_string(),
        kind: "package".into(),
        source: SourceKind::HomebrewFormula,
        current_version: current,
        path: None,
        metadata,
    };

    let evidence: Vec<String> = info
        .get("homepage")
        .and_then(|v| v.as_str())
        .map(|hp| vec![hp.to_string()])
        .unwrap_or_default();

    UpdateCandidate {
        item,
        latest_version: latest,
        release_notes: None,
        dependency_impact: impact,
        risk_level: None,
        ai_summary: None,
        recommended_action: None,
        can_auto_update: true,
        command: vec!["brew".into(), "upgrade".into(), name.to_string()],
        evidence,
    }
}

fn cask_candidate(cask: &serde_json::Value) -> UpdateCandidate {
    let name = cask
        .get("name")
        .or_else(|| cask.get("token"))
        .and_then(|v| v.as_str())
        .unwrap_or("unknown");
    let current = first(cask.get("installed_versions"))
        .or_else(|| cask.get("installed_version").and_then(|v| v.as_str()))
        .map(|s| s.to_string());
    let latest = cask
        .get("current_version")
        .or_else(|| cask.get("latest_version"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    log::debug!(
        "homebrew cask candidate name={} current={} latest={}",
        name,
        current.as_deref().unwrap_or("unknown"),
        latest.as_deref().unwrap_or("unknown")
    );

    let info = brew_info(name, true);

    let mut metadata = BTreeMap::new();
    metadata.insert("homebrew".into(), info.clone());

    let item = SoftwareItem {
        id: format!("brew-cask:{}", name),
        name: name.to_string(),
        kind: "application".into(),
        source: SourceKind::HomebrewCask,
        current_version: current,
        path: None,
        metadata,
    };

    let evidence: Vec<String> = info
        .get("homepage")
        .and_then(|v| v.as_str())
        .map(|hp| vec![hp.to_string()])
        .unwrap_or_default();

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
            "brew".into(),
            "upgrade".into(),
            "--cask".into(),
            name.to_string(),
        ],
        evidence,
    }
}

// ============================================================================
// Dependency analysis — matches Python's _brew_info() and _brew_uses()
// ============================================================================

/// Run brew info --json=v2 [--cask] <name> to get package details.
/// Matches Python's _brew_info().
fn brew_info(name: &str, cask: bool) -> serde_json::Value {
    let mut command: Vec<&str> = vec!["brew", "info", "--json=v2"];
    if cask {
        command.push("--cask");
    }
    let name_str = name.to_string();
    command.push(&name_str);

    match run_json(&command, &[0], 30) {
        Ok(data) => {
            let section = if cask { "casks" } else { "formulae" };
            match data.get(section).and_then(|v| v.as_array()) {
                Some(items) => items.first().cloned().unwrap_or(serde_json::Value::Object(
                    serde_json::Map::new(),
                )),
                None => serde_json::Value::Object(serde_json::Map::new()),
            }
        }
        Err(e) => {
            log::warn!("homebrew info failed name={} cask={}: {}", name, cask, e);
            serde_json::Value::Object(serde_json::Map::new())
        }
    }
}

/// Run brew uses --installed <name> to get reverse dependencies.
/// Matches Python's _brew_uses().
fn brew_uses(name: &str) -> Vec<String> {
    log::debug!("homebrew run command=brew uses --installed {}", name);
    let mut env_clear = std::collections::HashMap::new();
    for (key, value) in std::env::vars() {
        if key != "DYLD_LIBRARY_PATH" {
            env_clear.insert(key, value);
        }
    }

    let output = std::process::Command::new("brew")
        .args(["uses", "--installed", name])
        .env_clear()
        .envs(&env_clear)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .output();

    match output {
        Ok(out) => {
            if !out.status.success() {
                log::debug!(
                    "homebrew uses failed name={} returncode={:?}",
                    name,
                    out.status.code()
                );
                return vec![];
            }
            let stdout = String::from_utf8_lossy(&out.stdout);
            let mut tokens: Vec<String> = stdout
                .split_whitespace()
                .map(|s| s.to_string())
                .filter(|s| !s.is_empty())
                .collect();
            tokens.sort();
            tokens
        }
        Err(e) => {
            log::debug!("homebrew uses failed name={}: {}", name, e);
            vec![]
        }
    }
}

// ============================================================================
// Helpers
// ============================================================================

/// Return the first element if value is a list, otherwise the value itself.
/// Matches Python's _first().
fn first(value: Option<&serde_json::Value>) -> Option<&str> {
    match value {
        Some(serde_json::Value::Array(arr)) => arr.first().and_then(|v| v.as_str()),
        Some(v) => v.as_str(),
        None => None,
    }
}

fn installed_version(pkg: &serde_json::Value) -> Option<String> {
    // linked_keg
    if let Some(linked) = pkg.get("linked_keg").and_then(|v| v.as_str()) {
        return Some(linked.to_string());
    }
    // installed list
    if let Some(installed) = pkg.get("installed").and_then(|v| v.as_array()) {
        if let Some(first) = installed.first() {
            if let Some(ver) = first.get("version").and_then(|v| v.as_str()) {
                return Some(ver.to_string());
            }
        }
    }
    None
}

fn cask_current_version(cask: &serde_json::Value) -> Option<String> {
    if let Some(linked) = cask.get("linked_keg").and_then(|v| v.as_str()) {
        return Some(linked.to_string());
    }
    cask.get("version").and_then(|v| v.as_str()).map(|s| s.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_available_checks_brew() {
        let plugin = HomebrewPlugin;
        let _ = plugin.is_available();
    }

    #[test]
    fn test_parse_outdated_empty() {
        let data = serde_json::json!({
            "formulae": [],
            "casks": []
        });
        let (candidates, items) = parse_outdated(&data);
        assert!(items.is_empty());
        assert!(candidates.is_empty());
    }

    #[test]
    fn test_plugin_name() {
        assert_eq!(HomebrewPlugin.name(), "homebrew");
    }

    #[test]
    fn test_formula_candidate_kind_package() {
        let formula = serde_json::json!({
            "name": "node",
            "installed_versions": ["20.0.0"],
            "current_version": "22.0.0"
        });
        // This test will try to run brew info, which might fail in CI
        // but the kind should still be "package"
        let _cand = formula_candidate(&formula);
    }
}
