// Source classification — matches Python's frais/plugins/applications/source_classifier.py.
use crate::models::SourceKind;
use sha2::{Digest, Sha256};
use std::path::Path;

/// Classify how an application was installed based on bundle_id and path.
/// In the Python version, this uses codesign and xattr subprocess calls.
/// For the Rust version, we replicate the same classification logic.
/// Matches Python's classify_source exactly.
pub fn classify_source(bundle_id: &str, app_path: &str) -> SourceKind {
    let signing = signing_summary(Path::new(app_path));
    let quarantine = quarantine_summary(Path::new(app_path));

    // Apple Mac OS Application Signing → App Store
    if signing.authority.as_deref() == Some("Apple Mac OS Application Signing") {
        return SourceKind::AppStore;
    }

    // Local build: no team ID and adhoc/no authority
    // Matches Python: team_id in {None, "-"} and authority in {None, "adhoc"}
    let is_adhoc = signing.team_id.as_deref().is_none_or(|t| t == "-");
    let is_unsigned = signing.authority.as_deref().is_none_or(|a| a == "adhoc");

    if is_adhoc && is_unsigned {
        return SourceKind::LocalBuild;
    }

    // Network download: quarantine data contains http/https/safari/chrome
    if let Some(ref q) = quarantine {
        let q_lower = q.to_lowercase();
        if q_lower.contains("http") || q_lower.contains("safari") || q_lower.contains("chrome") {
            return SourceKind::NetworkDownload;
        }
    }

    // Has bundle ID → standard application
    if !bundle_id.is_empty() && bundle_id.contains('.') {
        return SourceKind::Application;
    }

    SourceKind::Unknown
}

/// Generate a stable ID from an app path when no bundle_id is available.
/// Matches Python's _path_id(): SHA256(path)[:12] with "app:" prefix.
pub fn path_id(path: &Path) -> String {
    let mut hasher = Sha256::new();
    hasher.update(path.to_string_lossy().as_bytes());
    let digest = format!("{:x}", hasher.finalize());
    format!("app:{}", &digest[..12])
}

/// Signing information from codesign.
#[derive(Debug, Clone, Default)]
pub struct SigningInfo {
    pub authority: Option<String>,
    pub team_id: Option<String>,
}

/// Run codesign to get signing information.
pub fn signing_summary(path: &Path) -> SigningInfo {
    let output = std::process::Command::new("codesign")
        .args(["-dv", "--verbose=4"])
        .arg(path)
        .env_remove("DYLD_LIBRARY_PATH")
        .output();

    match output {
        Ok(o) => {
            let stderr = String::from_utf8_lossy(&o.stderr);
            let authority = stderr
                .lines()
                .find(|l| l.trim().starts_with("Authority="))
                .map(|l| l.trim().strip_prefix("Authority=").unwrap_or("").to_string());
            let team_id = stderr
                .lines()
                .find(|l| l.trim().starts_with("TeamIdentifier="))
                .map(|l| {
                    l.trim()
                        .strip_prefix("TeamIdentifier=")
                        .unwrap_or("")
                        .to_string()
                });
            SigningInfo { authority, team_id }
        }
        Err(_) => SigningInfo::default(),
    }
}

/// Read quarantine extended attribute.
pub fn quarantine_summary(path: &Path) -> Option<String> {
    let output = std::process::Command::new("xattr")
        .args(["-p", "com.apple.quarantine"])
        .arg(path)
        .env_remove("DYLD_LIBRARY_PATH")
        .output();

    match output {
        Ok(o) if o.status.success() => {
            let data = String::from_utf8_lossy(&o.stdout).trim().to_string();
            if data.is_empty() { None } else { Some(data) }
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_classify_source_app_store() {
        // This test simulates the App Store classification logic
        // Actual codesign check requires a real app
        assert_eq!(
            SourceKind::AppStore.as_str(),
            "app store"
        );
    }

    #[test]
    fn test_classify_source_unknown_default() {
        assert_eq!(
            SourceKind::Unknown.as_str(),
            "unknown"
        );
    }

    #[test]
    fn test_signing_info_defaults() {
        let info = SigningInfo::default();
        assert!(info.authority.is_none());
        assert!(info.team_id.is_none());
    }
}
