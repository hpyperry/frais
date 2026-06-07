// App Store version checking — matches Python's frais/plugins/applications/app_store.py.
use crate::models::SoftwareItem;
use crate::models::SourceKind;

const ITUNES_SEARCH_URL: &str = "https://itunes.apple.com/lookup";

/// Query iTunes API and return the parsed JSON response.
/// Shared by check_app_store_version and resolve_app_store_command to avoid duplicate HTTP logic.
fn query_itunes(bundle_id: &str, item_name: &str) -> Option<serde_json::Value> {
    let url = format!("{}?bundleId={}&country=cn", ITUNES_SEARCH_URL, bundle_id);

    let client = match reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .user_agent(concat!("frais/", env!("CARGO_PKG_VERSION")))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            log::warn!("itunes api failed for {}: {}", item_name, e);
            return None;
        }
    };

    let response = match client.get(&url).send() {
        Ok(r) => r,
        Err(e) => {
            log::warn!("itunes api failed for {}: {}", item_name, e);
            return None;
        }
    };

    match response.json() {
        Ok(v) => Some(v),
        Err(e) => {
            log::warn!("itunes api failed for {}: {}", item_name, e);
            None
        }
    }
}

/// Query iTunes API for App Store app latest version and track ID.
/// Returns (version, track_id). Both None if not found or not an App Store app.
/// Matches Python's check_app_store_version exactly.
pub fn check_app_store_version(item: &SoftwareItem) -> (Option<String>, Option<u64>) {
    if item.source != SourceKind::AppStore {
        return (None, None);
    }

    let bundle_id = &item.id;
    if bundle_id.is_empty() || !bundle_id.contains('.') {
        return (None, None);
    }

    let body = match query_itunes(bundle_id, &item.name) {
        Some(v) => v,
        None => return (None, None),
    };

    let result_count = body
        .get("resultCount")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    if result_count == 0 {
        return (None, None);
    }

    let result = &body["results"][0];
    let version = result
        .get("version")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let track_id = result.get("trackId").and_then(|v| v.as_u64());

    if let Some(ref v) = version {
        log::info!(
            "itunes version for {}: {} (trackId={})",
            item.name,
            v,
            track_id.unwrap_or(0)
        );
    }

    (version, track_id)
}

/// Build the macappstore:// URL for an App Store app.
/// Matches Python's resolve_app_store_command.
pub fn resolve_app_store_command(item: &SoftwareItem) -> (Vec<String>, bool) {
    if item.source != SourceKind::AppStore {
        return (vec![], false);
    }

    let bundle_id = &item.id;
    if bundle_id.is_empty() || !bundle_id.contains('.') {
        return (vec![], false);
    }

    let body = match query_itunes(bundle_id, &item.name) {
        Some(v) => v,
        None => {
            log::debug!("itunes lookup failed for {}: api error", item.name);
            return (vec![], false);
        }
    };

    if body
        .get("resultCount")
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
        > 0
    {
        if let Some(track_id) = body["results"][0].get("trackId").and_then(|v| v.as_u64()) {
            return (
                vec![
                    "open".into(),
                    format!("macappstore://apps.apple.com/app/id{}", track_id),
                ],
                true,
            );
        }
    }

    (vec![], false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    #[test]
    fn test_returns_none_for_non_app_store() {
        let item = SoftwareItem {
            id: "com.example.app".into(),
            name: "Example".into(),
            kind: "application".into(),
            source: SourceKind::Application,
            current_version: None,
            path: None,
            metadata: BTreeMap::new(),
        };
        let (version, track_id) = check_app_store_version(&item);
        assert!(version.is_none());
        assert!(track_id.is_none());
    }

    #[test]
    fn test_returns_none_for_invalid_bundle_id() {
        let item = SoftwareItem {
            id: "invalid".into(),
            name: "Invalid".into(),
            kind: "application".into(),
            source: SourceKind::AppStore,
            current_version: None,
            path: None,
            metadata: BTreeMap::new(),
        };
        let (version, track_id) = check_app_store_version(&item);
        assert!(version.is_none());
        assert!(track_id.is_none());
    }

    #[test]
    fn test_returns_none_for_empty_bundle_id() {
        let item = SoftwareItem {
            id: "".into(),
            name: "Empty".into(),
            kind: "application".into(),
            source: SourceKind::AppStore,
            current_version: None,
            path: None,
            metadata: BTreeMap::new(),
        };
        let (version, track_id) = check_app_store_version(&item);
        assert!(version.is_none());
        assert!(track_id.is_none());
    }
}
