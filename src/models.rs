// Data models — matches Python's frais/models.py.
// All structs derive Serialize/Deserialize for JSON round-trip compatibility.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Source classification enum — matches Python's SourceKind(StrEnum).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SourceKind {
    Application,
    #[serde(rename = "local build")]
    LocalBuild,
    #[serde(rename = "network download")]
    NetworkDownload,
    #[serde(rename = "app store")]
    AppStore,
    #[serde(rename = "brew")]
    HomebrewFormula,
    #[serde(rename = "brew cask")]
    HomebrewCask,
    #[serde(rename = "npm")]
    NpmGlobal,
    #[serde(other)]
    Unknown,
}

impl SourceKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            SourceKind::Application => "application",
            SourceKind::LocalBuild => "local build",
            SourceKind::NetworkDownload => "network download",
            SourceKind::AppStore => "app store",
            SourceKind::HomebrewFormula => "brew",
            SourceKind::HomebrewCask => "brew cask",
            SourceKind::NpmGlobal => "npm",
            SourceKind::Unknown => "unknown",
        }
    }
}

/// System profile information — matches Python's SystemProfile dataclass.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SystemProfile {
    pub os_name: String,
    pub os_version: String,
    pub arch: String,
    pub applications_paths: Vec<String>,
}

impl SystemProfile {
    pub fn to_dict(&self) -> BTreeMap<String, serde_json::Value> {
        let mut m = BTreeMap::new();
        m.insert(
            "os_name".into(),
            serde_json::Value::String(self.os_name.clone()),
        );
        m.insert(
            "os_version".into(),
            serde_json::Value::String(self.os_version.clone()),
        );
        m.insert("arch".into(), serde_json::Value::String(self.arch.clone()));
        m.insert(
            "applications_paths".into(),
            serde_json::Value::Array(
                self.applications_paths
                    .iter()
                    .map(|p| serde_json::Value::String(p.clone()))
                    .collect(),
            ),
        );
        m
    }
}

/// A single installed software item — matches Python's SoftwareItem dataclass.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SoftwareItem {
    pub id: String,
    pub name: String,
    pub kind: String,
    pub source: SourceKind,
    pub current_version: Option<String>,
    pub path: Option<String>,
    #[serde(default)]
    pub metadata: BTreeMap<String, serde_json::Value>,
}

impl SoftwareItem {
    pub fn to_dict(&self) -> BTreeMap<String, serde_json::Value> {
        let mut m = BTreeMap::new();
        m.insert("id".into(), serde_json::Value::String(self.id.clone()));
        m.insert("name".into(), serde_json::Value::String(self.name.clone()));
        m.insert("kind".into(), serde_json::Value::String(self.kind.clone()));
        m.insert(
            "source".into(),
            serde_json::Value::String(self.source.as_str().to_string()),
        );
        m.insert(
            "current_version".into(),
            match &self.current_version {
                Some(v) => serde_json::Value::String(v.clone()),
                None => serde_json::Value::Null,
            },
        );
        m.insert(
            "path".into(),
            match &self.path {
                Some(p) => serde_json::Value::String(p.clone()),
                None => serde_json::Value::Null,
            },
        );
        m.insert(
            "metadata".into(),
            serde_json::to_value(&self.metadata).unwrap_or_default(),
        );
        m
    }

    /// Display-friendly source string for CLI output.
    /// Appends `[ios]` suffix for iPhone/iPad apps running on macOS.
    pub fn display_source(&self) -> String {
        let base = self.source.as_str();
        let is_ios = self
            .metadata
            .get("platform")
            .and_then(|v| v.as_str())
            .map(|p| p == "ios")
            .unwrap_or(false);
        if is_ios && self.source == SourceKind::AppStore {
            format!("{} [ios]", base)
        } else {
            base.to_string()
        }
    }
}

/// Result of LLM version research — matches Python's ResearchResult dataclass.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ResearchResult {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub latest_version: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub release_notes_url: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub download_url: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_repo_url: Option<String>,
    #[serde(default = "unknown_str")]
    pub confidence: String,
    #[serde(default)]
    pub evidence: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub release_notes: Option<String>,
}

fn unknown_str() -> String {
    "unknown".into()
}

impl Default for ResearchResult {
    fn default() -> Self {
        ResearchResult {
            latest_version: None,
            release_notes_url: None,
            download_url: None,
            source_repo_url: None,
            confidence: "unknown".into(),
            evidence: vec![],
            release_notes: None,
        }
    }
}

/// Dependency impact analysis — matches Python's DependencyImpact dataclass.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct DependencyImpact {
    #[serde(default)]
    pub used_by: Vec<String>,
    #[serde(default)]
    pub depends_on: Vec<String>,
    #[serde(default = "unknown_str")]
    pub impact_level: String,
}

impl Default for DependencyImpact {
    fn default() -> Self {
        DependencyImpact {
            used_by: vec![],
            depends_on: vec![],
            impact_level: "unknown".into(),
        }
    }
}

impl DependencyImpact {
    pub fn to_dict(&self) -> BTreeMap<String, serde_json::Value> {
        let mut m = BTreeMap::new();
        m.insert(
            "used_by".into(),
            serde_json::Value::Array(
                self.used_by
                    .iter()
                    .map(|v| serde_json::Value::String(v.clone()))
                    .collect(),
            ),
        );
        m.insert(
            "depends_on".into(),
            serde_json::Value::Array(
                self.depends_on
                    .iter()
                    .map(|v| serde_json::Value::String(v.clone()))
                    .collect(),
            ),
        );
        m.insert(
            "impact_level".into(),
            serde_json::Value::String(self.impact_level.clone()),
        );
        m
    }
}

/// An update candidate — matches Python's UpdateCandidate dataclass.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpdateCandidate {
    pub item: SoftwareItem,
    #[serde(default)]
    pub latest_version: Option<String>,
    #[serde(default)]
    pub release_notes: Option<String>,
    #[serde(default)]
    pub dependency_impact: DependencyImpact,
    #[serde(default)]
    pub risk_level: Option<String>,
    #[serde(default)]
    pub ai_summary: Option<String>,
    #[serde(default)]
    pub recommended_action: Option<String>,
    #[serde(default)]
    pub can_auto_update: bool,
    #[serde(default)]
    pub command: Vec<String>,
    #[serde(default)]
    pub evidence: Vec<String>,
}

impl UpdateCandidate {
    pub fn to_dict(&self) -> BTreeMap<String, serde_json::Value> {
        let mut m = BTreeMap::new();
        m.insert(
            "item".into(),
            serde_json::to_value(&self.item).unwrap_or_default(),
        );
        m.insert("latest_version".into(), opt_str(&self.latest_version));
        m.insert("release_notes".into(), opt_str(&self.release_notes));
        m.insert(
            "dependency_impact".into(),
            serde_json::to_value(&self.dependency_impact).unwrap_or_default(),
        );
        m.insert("risk_level".into(), opt_str(&self.risk_level));
        m.insert("ai_summary".into(), opt_str(&self.ai_summary));
        m.insert(
            "recommended_action".into(),
            opt_str(&self.recommended_action),
        );
        m.insert(
            "can_auto_update".into(),
            serde_json::Value::Bool(self.can_auto_update),
        );
        m.insert(
            "command".into(),
            serde_json::Value::Array(
                self.command
                    .iter()
                    .map(|c| serde_json::Value::String(c.clone()))
                    .collect(),
            ),
        );
        m.insert(
            "evidence".into(),
            serde_json::Value::Array(
                self.evidence
                    .iter()
                    .map(|e| serde_json::Value::String(e.clone()))
                    .collect(),
            ),
        );
        m
    }
}

fn opt_str(v: &Option<String>) -> serde_json::Value {
    match v {
        Some(s) => serde_json::Value::String(s.clone()),
        None => serde_json::Value::Null,
    }
}

/// Result from a single plugin scan — matches Python's PluginScanResult dataclass.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PluginScanResult {
    #[serde(default)]
    pub items: Vec<SoftwareItem>,
    #[serde(default)]
    pub candidates: Vec<UpdateCandidate>,
    #[serde(default)]
    pub skipped: Vec<String>,
}

impl PluginScanResult {
    pub fn to_dict(&self) -> BTreeMap<String, serde_json::Value> {
        let mut m = BTreeMap::new();
        m.insert(
            "items".into(),
            serde_json::to_value(&self.items).unwrap_or_default(),
        );
        m.insert(
            "candidates".into(),
            serde_json::to_value(&self.candidates).unwrap_or_default(),
        );
        m.insert(
            "skipped".into(),
            serde_json::Value::Array(
                self.skipped
                    .iter()
                    .map(|s| serde_json::Value::String(s.clone()))
                    .collect(),
            ),
        );
        m
    }
}

/// Full scan result — matches Python's ScanResult dataclass.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScanResult {
    pub system: SystemProfile,
    #[serde(default)]
    pub plugin_results: BTreeMap<String, PluginScanResult>,
}

impl ScanResult {
    /// Aggregate all candidates across all plugins — matches Python's all_candidates property.
    pub fn all_candidates(&self) -> Vec<&UpdateCandidate> {
        self.plugin_results
            .values()
            .flat_map(|pr| pr.candidates.iter())
            .collect()
    }

    pub fn to_dict(&self) -> BTreeMap<String, serde_json::Value> {
        let mut m = BTreeMap::new();
        m.insert(
            "system".into(),
            serde_json::to_value(&self.system).unwrap_or_default(),
        );
        m.insert(
            "plugin_results".into(),
            serde_json::to_value(&self.plugin_results).unwrap_or_default(),
        );
        m
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_source_kind_serde_round_trip() {
        let variants = [
            SourceKind::Application,
            SourceKind::LocalBuild,
            SourceKind::NetworkDownload,
            SourceKind::AppStore,
            SourceKind::HomebrewFormula,
            SourceKind::HomebrewCask,
            SourceKind::NpmGlobal,
            SourceKind::Unknown,
        ];
        for v in &variants {
            let json = serde_json::to_string(v).unwrap();
            let restored: SourceKind = serde_json::from_str(&json).unwrap();
            assert_eq!(*v, restored, "Failed round-trip for {:?}", v);
        }
    }

    #[test]
    fn test_software_item_serde_round_trip() {
        let item = SoftwareItem {
            id: "com.example.app".into(),
            name: "Example".into(),
            kind: "application".into(),
            source: SourceKind::Application,
            current_version: Some("1.0.0".into()),
            path: Some("/Applications/Example.app".into()),
            metadata: BTreeMap::new(),
        };
        let json = serde_json::to_string(&item).unwrap();
        let restored: SoftwareItem = serde_json::from_str(&json).unwrap();
        assert_eq!(restored.id, item.id);
        assert_eq!(restored.name, item.name);
        assert_eq!(restored.source, item.source);
        assert_eq!(restored.current_version, item.current_version);
    }

    #[test]
    fn test_update_candidate_serde_round_trip() {
        let item = SoftwareItem {
            id: "node".into(),
            name: "Node.js".into(),
            kind: "formula".into(),
            source: SourceKind::HomebrewFormula,
            current_version: Some("20.0.0".into()),
            path: None,
            metadata: BTreeMap::new(),
        };
        let candidate = UpdateCandidate {
            item,
            latest_version: Some("22.0.0".into()),
            release_notes: None,
            dependency_impact: DependencyImpact::default(),
            risk_level: Some("low".into()),
            ai_summary: None,
            recommended_action: Some("Update".into()),
            can_auto_update: true,
            command: vec!["brew".into(), "upgrade".into(), "node".into()],
            evidence: vec![],
        };
        let json = serde_json::to_string(&candidate).unwrap();
        let restored: UpdateCandidate = serde_json::from_str(&json).unwrap();
        assert_eq!(restored.latest_version, candidate.latest_version);
        assert_eq!(restored.can_auto_update, candidate.can_auto_update);
        assert_eq!(restored.command, candidate.command);
        assert_eq!(restored.item.id, candidate.item.id);
    }

    #[test]
    fn test_plugin_scan_result_serde() {
        let psr = PluginScanResult {
            items: vec![],
            candidates: vec![],
            skipped: vec!["brew not found".into()],
        };
        let json = serde_json::to_string(&psr).unwrap();
        let restored: PluginScanResult = serde_json::from_str(&json).unwrap();
        assert_eq!(restored.skipped, psr.skipped);
    }

    #[test]
    fn test_scan_result_all_candidates() {
        let item = SoftwareItem {
            id: "test.app".into(),
            name: "Test".into(),
            kind: "app".into(),
            source: SourceKind::Application,
            current_version: Some("1.0".into()),
            path: None,
            metadata: BTreeMap::new(),
        };
        let candidate = UpdateCandidate {
            item,
            latest_version: Some("2.0".into()),
            release_notes: None,
            dependency_impact: DependencyImpact::default(),
            risk_level: None,
            ai_summary: None,
            recommended_action: None,
            can_auto_update: false,
            command: vec![],
            evidence: vec![],
        };
        let mut pr = BTreeMap::new();
        pr.insert(
            "test".into(),
            PluginScanResult {
                items: vec![],
                candidates: vec![candidate],
                skipped: vec![],
            },
        );
        let sr = ScanResult {
            system: SystemProfile {
                os_name: "macOS".into(),
                os_version: "15.0".into(),
                arch: "arm64".into(),
                applications_paths: vec!["/Applications".into()],
            },
            plugin_results: pr,
        };
        assert_eq!(sr.all_candidates().len(), 1);
    }

    #[test]
    fn test_system_profile_to_dict() {
        let sp = SystemProfile {
            os_name: "macOS".into(),
            os_version: "15.0".into(),
            arch: "arm64".into(),
            applications_paths: vec!["/Applications".into()],
        };
        let d = sp.to_dict();
        assert_eq!(
            d.get("os_name").unwrap(),
            &serde_json::Value::String("macOS".into())
        );
    }

    #[test]
    fn test_dependency_impact_defaults() {
        let di = DependencyImpact::default();
        assert!(di.used_by.is_empty());
        assert!(di.depends_on.is_empty());
        assert_eq!(di.impact_level, "unknown");
    }

    #[test]
    fn test_research_result_defaults() {
        let rr = ResearchResult::default();
        assert_eq!(rr.confidence, "unknown");
        assert!(rr.evidence.is_empty());
        assert_eq!(rr.latest_version, None);
    }
}
