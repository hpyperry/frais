// Plugin system base — matches Python's frais/plugins/base.py and __init__.py.
pub mod applications;
pub mod homebrew;
pub mod npm;
pub mod registry;
pub mod subprocess_json;

use crate::llm::base::{LLMClient, LLMRequestError};
use crate::models::{PluginScanResult, SystemProfile, UpdateCandidate};

/// Chinese summary prompt — matches Python's _SUMMARIZE_PROMPT in commands/summarize.py.
const SUMMARIZE_PROMPT: &str =
    "You are helping a macOS user decide whether to update installed software. \
     Write a concise update recommendation in Chinese.\n\
     \n\
     Rules:\n\
     - Output 3-4 short bullet lines (each starting with \"- \"), no preamble or closing.\n\
     - Use **bold** for version numbers, risk levels, and key actions.\n\
     - Mention: what changed, risk level, dependency impact (if any), and a clear recommendation.\n\
     - If the evidence includes URLs, reference the most credible one.\n\
     - Never invent version numbers, CVEs, or changelog details not present in the data.\n\
     - If evidence is weak or missing, say so honestly — prefer \"信息不足\" over guessing.";

/// Build the user prompt for generating an update recommendation.
/// Matches Python's build_summary_prompt() in commands/summarize.py.
pub fn build_summary_prompt(candidate: &UpdateCandidate) -> String {
    let item = &candidate.item;
    let dep = &candidate.dependency_impact;
    let dep_count = dep.depends_on.len();
    let used_by_count = dep.used_by.len();
    let evidence = serde_json::to_string(&candidate.evidence).unwrap_or_default();
    let command_str = if candidate.command.is_empty() {
        "(manual)".to_string()
    } else {
        candidate.command.join(" ")
    };
    format!(
        "{}\n\n\
         Name: {}\n\
         Type: {} ({})\n\
         Current version: {}\n\
         Latest version: {}\n\
         Risk level: {}\n\
         Auto-update available: {}\n\
         Update command: {}\n\
         Depends on: {} ({})\n\
         Used by: {} ({})\n\
         Evidence: {}\n\
         Release notes: {}",
        SUMMARIZE_PROMPT,
        item.name,
        item.kind,
        item.source.as_str(),
        item.current_version.as_deref().unwrap_or("unknown"),
        candidate.latest_version.as_deref().unwrap_or("unknown"),
        candidate.risk_level.as_deref().unwrap_or("unknown"),
        candidate.can_auto_update,
        command_str,
        dep_count,
        dep.depends_on.join(", "),
        used_by_count,
        dep.used_by.join(", "),
        evidence,
        candidate.release_notes.as_deref().unwrap_or("(none)"),
    )
}

/// ScannerPlugin trait — matches Python's ScannerPlugin ABC.
/// Each scanner is a struct implementing this trait.
pub trait ScannerPlugin: Send + Sync {
    /// Unique plugin name (e.g. "applications", "homebrew", "npm").
    fn name(&self) -> &'static str;

    /// Whether this plugin is enabled by default.
    fn enabled_by_default(&self) -> bool {
        false
    }

    /// Rich display color name (for CLI output styling).
    fn display_color(&self) -> &'static str {
        "white"
    }

    /// Ordered step labels for progress reporting.
    fn scan_steps(&self) -> &'static [&'static str] {
        &[]
    }

    /// Whether the underlying tool is available on this system.
    fn is_available(&self) -> bool;

    /// Scan for outdated software only. Returns items and candidates.
    /// The on_progress callback is Sync so plugins can call it from parallel workers.
    fn scan(
        &self,
        system: &SystemProfile,
        on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
        max_workers: usize,
    ) -> PluginScanResult;

    /// Scan ALL installed software (not just outdated).
    /// Default: delegates to scan().
    fn scan_all(
        &self,
        system: &SystemProfile,
        on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
        max_workers: usize,
    ) -> PluginScanResult {
        self.scan(system, on_progress, max_workers)
    }

    /// Execute an update for a candidate.
    /// Default: runs candidate.command via subprocess if can_auto_update.
    fn update(&self, candidate: &UpdateCandidate) -> bool {
        if candidate.can_auto_update && !candidate.command.is_empty() {
            std::process::Command::new(&candidate.command[0])
                .args(&candidate.command[1..])
                .status()
                .map(|s| s.success())
                .unwrap_or(false)
        } else {
            false
        }
    }

    /// Generate AI summary for a candidate.
    /// Default: uses summarize_candidate() with Chinese prompt.
    /// Matches Python's ScannerPlugin.summarize() → summarize_candidate().
    fn summarize(
        &self,
        agent: &dyn LLMClient,
        candidate: &mut UpdateCandidate,
    ) -> Result<(), LLMRequestError> {
        if candidate.ai_summary.is_some() {
            return Ok(());
        }
        let prompt = build_summary_prompt(candidate);
        let summary = agent.chat("", &prompt, None, false)?;
        candidate.ai_summary = Some(summary);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::{SoftwareItem, SourceKind, DependencyImpact};
    use std::collections::BTreeMap;

    struct TestPlugin {
        did_scan: std::sync::Mutex<bool>,
    }

    impl ScannerPlugin for TestPlugin {
        fn name(&self) -> &'static str {
            "test"
        }
        fn enabled_by_default(&self) -> bool {
            true
        }
        fn is_available(&self) -> bool {
            true
        }
        fn scan(
            &self,
            _system: &SystemProfile,
            _on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
            _max_workers: usize,
        ) -> PluginScanResult {
            *self.did_scan.lock().unwrap() = true;
            PluginScanResult::default()
        }
    }

    #[test]
    fn test_scan_all_default_delegates_to_scan() {
        let plugin = TestPlugin {
            did_scan: std::sync::Mutex::new(false),
        };
        let system = SystemProfile {
            os_name: "macOS".into(),
            os_version: "15.0".into(),
            arch: "arm64".into(),
            applications_paths: vec![],
        };
        plugin.scan_all(&system, None, 1);
        assert!(*plugin.did_scan.lock().unwrap());
    }

    #[test]
    fn test_update_default_runs_command_when_can_auto_update() {
        let plugin = TestPlugin {
            did_scan: std::sync::Mutex::new(false),
        };
        let candidate = UpdateCandidate {
            item: SoftwareItem {
                id: "test".into(),
                name: "test".into(),
                kind: "test".into(),
                source: SourceKind::Unknown,
                current_version: None,
                path: None,
                metadata: BTreeMap::new(),
            },
            latest_version: None,
            release_notes: None,
            dependency_impact: DependencyImpact::default(),
            risk_level: None,
            ai_summary: None,
            recommended_action: None,
            can_auto_update: true,
            command: vec!["echo".into(), "hello".into()],
            evidence: vec![],
        };
        assert!(plugin.update(&candidate));
    }

    #[test]
    fn test_update_default_skips_when_cannot_auto_update() {
        let plugin = TestPlugin {
            did_scan: std::sync::Mutex::new(false),
        };
        let candidate = UpdateCandidate {
            item: SoftwareItem {
                id: "test".into(),
                name: "test".into(),
                kind: "test".into(),
                source: SourceKind::Unknown,
                current_version: None,
                path: None,
                metadata: BTreeMap::new(),
            },
            latest_version: None,
            release_notes: None,
            dependency_impact: DependencyImpact::default(),
            risk_level: None,
            ai_summary: None,
            recommended_action: None,
            can_auto_update: false,
            command: vec![],
            evidence: vec![],
        };
        assert!(!plugin.update(&candidate));
    }
}
