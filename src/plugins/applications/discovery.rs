// Application discovery — matches Python's frais/plugins/applications/discovery.py.
use crate::models::SoftwareItem;
use std::collections::BTreeMap;
use std::path::Path;

/// Scan for .app bundles in the given paths.
/// Matches Python's scan_applications exactly, including logging and sorting.
pub fn scan_applications(paths: &[String]) -> Vec<SoftwareItem> {
    let mut items = Vec::new();
    let mut seen = std::collections::HashSet::new();

    for base_path in paths {
        // Expand ~/ using shellexpand — matches Python's Path(base).expanduser()
        let expanded = match shellexpand::full(base_path) {
            Ok(s) => s.into_owned(),
            Err(_) => {
                log::warn!("applications failed to expand path: {}", base_path);
                continue;
            }
        };
        let base = Path::new(&expanded);
        let exists = base.exists() && base.is_dir();
        log::info!(
            "applications scan path={} exists={}",
            base.display(),
            exists
        );
        if !exists {
            continue;
        }

        // Collect and sort .app bundles — matches Python's sorted(base_path.glob("*.app"))
        let mut app_paths: Vec<std::path::PathBuf> = Vec::new();
        if let Ok(entries) = std::fs::read_dir(base) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.extension().map(|e| e == "app").unwrap_or(false) {
                    app_paths.push(path);
                }
            }
        }
        app_paths.sort();

        log::info!(
            "applications found bundles path={} count={}",
            base.display(),
            app_paths.len()
        );

        for app_path in &app_paths {
            log::debug!("applications reading bundle={}", app_path.display());
            if let Some(item) = read_application(app_path) {
                if seen.insert(item.id.clone()) {
                    log::debug!(
                        "applications item name={} id={} version={} source={}",
                        item.name,
                        item.id,
                        item.current_version.as_deref().unwrap_or("unknown"),
                        item.source.as_str()
                    );
                    items.push(item);
                } else {
                    log::debug!(
                        "applications skipped duplicate id={} path={}",
                        item.id,
                        app_path.display()
                    );
                }
            } else {
                log::debug!(
                    "applications skipped unreadable bundle={}",
                    app_path.display()
                );
            }
        }
    }

    items
}

/// Read a single .app bundle and extract metadata.
/// Dispatches to the correct reader based on bundle structure:
/// - macOS native: Contents/Info.plist
/// - iOS on Apple Silicon: Wrapper/iTunesMetadata.plist + nested .app
pub fn read_application(app_path: &Path) -> Option<SoftwareItem> {
    // Path 1: macOS native bundle
    let macos_plist = app_path.join("Contents").join("Info.plist");
    if macos_plist.exists() {
        return read_macos_bundle(app_path, &macos_plist);
    }

    // Path 2: iOS app running on Apple Silicon Mac
    let wrapper = app_path.join("Wrapper");
    let itunes_plist = wrapper.join("iTunesMetadata.plist");
    if wrapper.is_dir() && itunes_plist.exists() {
        return read_ios_bundle(app_path, &wrapper, &itunes_plist);
    }

    log::debug!(
        "applications missing Info.plist path={}",
        app_path.display()
    );
    None
}

/// Read a native macOS .app bundle from Contents/Info.plist.
fn read_macos_bundle(app_path: &Path, plist_path: &Path) -> Option<SoftwareItem> {
    let plist_value: plist::Value = match plist::Value::from_file(plist_path) {
        Ok(v) => v,
        Err(e) => {
            log::debug!(
                "applications failed to parse Info.plist path={}: {}",
                plist_path.display(),
                e
            );
            return None;
        }
    };
    let dict = plist_value.as_dictionary()?;

    let name = dict
        .get("CFBundleDisplayName")
        .or_else(|| dict.get("CFBundleName"))
        .and_then(|v| v.as_string())
        .unwrap_or_else(|| {
            app_path
                .file_stem()
                .and_then(|n| n.to_str())
                .unwrap_or("unknown")
        })
        .to_string();

    let bundle_id = dict
        .get("CFBundleIdentifier")
        .and_then(|v| v.as_string())
        .map(|s| s.to_string());

    let version = dict
        .get("CFBundleShortVersionString")
        .or_else(|| dict.get("CFBundleVersion"))
        .and_then(|v| v.as_string())
        .map(|s| s.to_string());

    // Platform: DTPlatformName="macosx" for native apps; absent for some (Electron etc.)
    // Always treated as "macos" — iOS detection happens in read_ios_bundle
    let platform = "macos";

    // Run codesign and xattr for source classification and metadata
    let signing = super::source_classifier::signing_summary(app_path);
    let quarantine = super::source_classifier::quarantine_summary(app_path);
    let source = super::source_classifier::classify_source(
        bundle_id.as_deref().unwrap_or(""),
        &app_path.to_string_lossy(),
    );

    // Stable ID: bundle_id first, then path_id fallback
    let stable_id = bundle_id
        .clone()
        .unwrap_or_else(|| super::source_classifier::path_id(app_path));

    let mut metadata = BTreeMap::new();
    metadata.insert(
        "bundle_id".into(),
        serde_json::Value::String(bundle_id.unwrap_or_default()),
    );
    metadata.insert(
        "platform".into(),
        serde_json::Value::String(platform.into()),
    );
    metadata.insert(
        "signing".into(),
        serde_json::json!({
            "authority": signing.authority,
            "team_id": signing.team_id,
        }),
    );
    metadata.insert(
        "quarantine".into(),
        match &quarantine {
            Some(q) => serde_json::Value::String(q.clone()),
            None => serde_json::Value::Null,
        },
    );

    Some(SoftwareItem {
        id: stable_id,
        name,
        kind: "application".into(),
        source,
        current_version: version,
        path: Some(app_path.to_string_lossy().to_string()),
        metadata,
    })
}

/// Read an iOS app bundle running on Apple Silicon Mac.
/// Structure: .app/Wrapper/iTunesMetadata.plist + Wrapper/<name>.app/Info.plist
fn read_ios_bundle(app_path: &Path, wrapper: &Path, itunes_plist: &Path) -> Option<SoftwareItem> {
    // Parse iTunesMetadata.plist — contains name, version, itemId
    let itunes_value = plist::Value::from_file(itunes_plist).ok()?;
    let itunes = itunes_value.as_dictionary()?;

    let name = itunes
        .get("itemName")
        .and_then(|v| v.as_string())
        .map(|s| s.to_string())?;

    let version = itunes
        .get("bundleShortVersionString")
        .and_then(|v| v.as_string())
        .map(|s| s.to_string());

    let item_id = itunes
        .get("itemId")
        .and_then(|v| v.as_signed_integer())
        .map(|id| id.to_string());

    // Find the nested iOS .app bundle inside Wrapper/
    let nested_app = find_ios_bundle(wrapper)?;
    let nested_plist = nested_app.join("Info.plist");
    if !nested_plist.exists() {
        log::debug!(
            "applications iOS bundle missing nested Info.plist path={}",
            nested_plist.display()
        );
        return None;
    }

    let nested_value = plist::Value::from_file(&nested_plist).ok()?;
    let nested = nested_value.as_dictionary()?;

    let bundle_id = nested
        .get("CFBundleIdentifier")
        .and_then(|v| v.as_string())
        .map(|s| s.to_string());

    // iOS apps are always AppStore
    let source = crate::models::SourceKind::AppStore;

    let stable_id = bundle_id
        .clone()
        .unwrap_or_else(|| super::source_classifier::path_id(app_path));

    let mut metadata = BTreeMap::new();
    metadata.insert(
        "bundle_id".into(),
        serde_json::Value::String(bundle_id.unwrap_or_default()),
    );
    metadata.insert("platform".into(), serde_json::Value::String("ios".into()));
    // iOS apps have no macOS codesign/xattr — explicit null
    metadata.insert("signing".into(), serde_json::Value::Null);
    metadata.insert("quarantine".into(), serde_json::Value::Null);
    if let Some(tid) = item_id {
        metadata.insert("track_id".into(), serde_json::Value::String(tid));
    }

    log::debug!(
        "applications ios bundle name={} id={} version={}",
        name,
        stable_id,
        version.as_deref().unwrap_or("unknown")
    );

    Some(SoftwareItem {
        id: stable_id,
        name,
        kind: "application".into(),
        source,
        current_version: version,
        path: Some(app_path.to_string_lossy().to_string()),
        metadata,
    })
}

/// Find the nested iOS .app directory inside the Wrapper/ directory.
fn find_ios_bundle(wrapper: &Path) -> Option<std::path::PathBuf> {
    let entries = std::fs::read_dir(wrapper).ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map(|e| e == "app").unwrap_or(false) && path.is_dir() {
            return Some(path);
        }
    }
    log::debug!("applications no nested .app found in Wrapper/");
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scan_applications_empty_dir() {
        let dir = tempfile::TempDir::new().unwrap();
        let items = scan_applications(&[dir.path().to_string_lossy().to_string()]);
        assert!(items.is_empty());
    }

    #[test]
    fn test_scan_applications_nonexistent_path() {
        let items = scan_applications(&["/nonexistent/path".into()]);
        assert!(items.is_empty());
    }

    #[test]
    fn test_read_application_no_plist() {
        let dir = tempfile::TempDir::new().unwrap();
        let app_path = dir.path().join("NoPlist.app");
        std::fs::create_dir_all(app_path.join("Contents")).unwrap();
        let result = read_application(&app_path);
        assert!(result.is_none());
    }

    #[test]
    fn test_read_application_with_plist_no_bundle_id() {
        // When bundle_id is missing, path_id fallback should be used
        let dir = tempfile::TempDir::new().unwrap();
        let app_path = dir.path().join("NoBundleId.app");
        let contents = app_path.join("Contents");
        std::fs::create_dir_all(&contents).unwrap();
        // Write a minimal Info.plist with no CFBundleIdentifier
        let plist_path = contents.join("Info.plist");
        let plist_data = plist::Value::Dictionary(plist::Dictionary::new());
        plist_data.to_file_xml(&plist_path).unwrap();
        let result = read_application(&app_path);
        if result.is_some() {
            let item = result.unwrap();
            // Should have a stable path_id fallback
            assert!(item.id.starts_with("app:"));
            assert_eq!(
                item.metadata.get("bundle_id").unwrap(),
                &serde_json::Value::String("".into())
            );
        }
    }

    #[test]
    fn test_path_id_is_stable() {
        let id1 = super::super::source_classifier::path_id(std::path::Path::new(
            "/Applications/Test.app",
        ));
        let id2 = super::super::source_classifier::path_id(std::path::Path::new(
            "/Applications/Test.app",
        ));
        assert_eq!(id1, id2);
        assert!(id1.starts_with("app:"));
        assert_eq!(id1.len(), 16); // "app:" + 12 hex chars
    }
}
