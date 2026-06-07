// UpdateCandidate factory — matches Python's research/candidate_factory.py.
use crate::models::{ResearchResult, SoftwareItem, SourceKind, UpdateCandidate};

/// Build an UpdateCandidate from research results.
/// Matches Python's _make_candidate() in research/candidate_factory.py.
pub fn make_candidate(
    item: SoftwareItem,
    latest_version: String,
    result: Option<&ResearchResult>,
    source: &str,
    app_store_id: Option<u64>,
) -> UpdateCandidate {
    let command: Vec<String> = if item.source == SourceKind::AppStore {
        match app_store_id {
            Some(id) => {
                vec![
                    "open".into(),
                    format!("macappstore://apps.apple.com/app/id{}", id),
                ]
            }
            None => vec![],
        }
    } else if item.source == SourceKind::HomebrewFormula {
        vec!["brew".into(), "upgrade".into(), item.name.clone()]
    } else if item.source == SourceKind::HomebrewCask {
        vec![
            "brew".into(),
            "upgrade".into(),
            "--cask".into(),
            item.name.clone(),
        ]
    } else {
        vec![]
    };

    UpdateCandidate {
        item,
        latest_version: Some(latest_version),
        release_notes: result.and_then(|r| r.release_notes.clone()),
        dependency_impact: crate::models::DependencyImpact::default(),
        risk_level: None,
        ai_summary: None,
        recommended_action: None,
        can_auto_update: !command.is_empty(),
        command,
        evidence: result
            .map(|r| r.evidence.clone())
            .unwrap_or_else(|| vec![format!("Source: {}", source)]),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn test_item(source: SourceKind) -> SoftwareItem {
        SoftwareItem {
            id: "test.app".into(),
            name: "test".into(),
            kind: "app".into(),
            source,
            current_version: Some("1.0.0".into()),
            path: None,
            metadata: BTreeMap::new(),
        }
    }

    #[test]
    fn test_make_candidate_homebrew_formula() {
        let c = make_candidate(
            test_item(SourceKind::HomebrewFormula),
            "2.0.0".into(),
            None,
            "brew",
            None,
        );
        assert!(c.can_auto_update);
        assert_eq!(c.command, vec!["brew", "upgrade", "test"]);
        assert_eq!(c.latest_version, Some("2.0.0".into()));
        assert_eq!(c.evidence, vec!["Source: brew"]);
    }

    #[test]
    fn test_make_candidate_local_build() {
        let c = make_candidate(
            test_item(SourceKind::LocalBuild),
            "2.0.0".into(),
            None,
            "llm",
            None,
        );
        assert!(!c.can_auto_update);
        assert!(c.command.is_empty());
        assert_eq!(c.evidence, vec!["Source: llm"]);
    }

    #[test]
    fn test_make_candidate_npm() {
        // Python's _make_candidate() does NOT handle npm — NpmPlugin has its own _make_candidate().
        let c = make_candidate(
            test_item(SourceKind::NpmGlobal),
            "2.0.0".into(),
            None,
            "npm",
            None,
        );
        assert!(!c.can_auto_update);
        assert!(c.command.is_empty());
    }

    #[test]
    fn test_make_candidate_app_store() {
        let c = make_candidate(
            test_item(SourceKind::AppStore),
            "2.0.0".into(),
            None,
            "itunes",
            Some(12345),
        );
        assert!(c.can_auto_update);
        assert_eq!(c.command[0], "open");
        assert!(c.command[1].contains("macappstore"));
        assert!(c.command[1].contains("12345"));
    }

    #[test]
    fn test_make_candidate_app_store_no_track_id() {
        let c = make_candidate(
            test_item(SourceKind::AppStore),
            "2.0.0".into(),
            None,
            "itunes",
            None,
        );
        assert!(!c.can_auto_update);
        assert!(c.command.is_empty());
    }

    #[test]
    fn test_make_candidate_with_result_evidence() {
        let result = ResearchResult {
            latest_version: Some("2.0.0".into()),
            release_notes_url: None,
            download_url: None,
            source_repo_url: None,
            confidence: "high".into(),
            evidence: vec!["https://example.com/releases".into()],
            release_notes: Some("Bug fixes".into()),
        };
        let c = make_candidate(
            test_item(SourceKind::Application),
            "2.0.0".into(),
            Some(&result),
            "llm",
            None,
        );
        assert_eq!(c.evidence, vec!["https://example.com/releases"]);
        assert_eq!(c.release_notes, Some("Bug fixes".into()));
    }
}
