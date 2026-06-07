// Version comparison — matches Python's plugins/applications/research/version_compare.py.
// Uses semver crate for Version parsing with digit-only fallback.

use semver::Version;

/// Check if `latest` is newer than `current`. Returns false if either is empty.
/// Matches Python's _is_newer exactly.
pub fn is_newer(current: Option<&str>, latest: Option<&str>) -> bool {
    let current = match current {
        Some(c) if !c.is_empty() => c,
        _ => return false,
    };
    let latest = match latest {
        Some(l) if !l.is_empty() => l,
        _ => return false,
    };

    let cur = normalize(current);
    let lat = normalize(latest);

    if cur == lat {
        return false;
    }

    // Try semver parsing first
    if let (Ok(vc), Ok(vl)) = (Version::parse(&cur), Version::parse(&lat)) {
        return vl > vc;
    }

    // Fallback: digit-only comparison
    let c2 = digits_only(&cur);
    let l2 = digits_only(&lat);

    if c2 == l2 {
        return false;
    }

    if let (Ok(vc), Ok(vl)) = (Version::parse(&c2), Version::parse(&l2)) {
        return vl > vc;
    }

    // Last resort: integer tuple comparison
    let l_parts: Vec<u64> = l2.split('.').filter_map(|s| s.parse().ok()).collect();
    let c_parts: Vec<u64> = c2.split('.').filter_map(|s| s.parse().ok()).collect();

    if l_parts.is_empty() || c_parts.is_empty() {
        return false;
    }

    l_parts > c_parts
}

/// Normalize a version string: strip all leading v/V, parentheticals, space suffixes.
/// Matches Python's _normalize: `v.strip().lstrip("vV")` then strip at " " or "(".
fn normalize(value: &str) -> String {
    let v = value.trim().trim_start_matches(['v', 'V']);

    // Find first space or opening paren and truncate
    if let Some(idx) = v.find([' ', '(']) {
        v[..idx].to_string()
    } else {
        v.to_string()
    }
}

/// Keep only digits and dots.
fn digits_only(value: &str) -> String {
    value.chars().filter(|c| c.is_ascii_digit() || *c == '.').collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_newer_detects_upgrade() {
        assert!(is_newer(Some("1.0.0"), Some("2.0.0")));
    }

    #[test]
    fn test_is_newer_rejects_same_version() {
        assert!(!is_newer(Some("1.0.0"), Some("1.0.0")));
    }

    #[test]
    fn test_is_newer_rejects_downgrade() {
        assert!(!is_newer(Some("10.0.0"), Some("2.0.0")));
    }

    #[test]
    fn test_is_newer_with_v_prefix() {
        assert!(is_newer(Some("v1.0.0"), Some("v2.0.0")));
    }

    #[test]
    fn test_is_newer_handles_none_current() {
        assert!(!is_newer(None, Some("2.0.0")));
    }

    #[test]
    fn test_is_newer_handles_none_latest() {
        assert!(!is_newer(Some("1.0.0"), None));
    }

    #[test]
    fn test_is_newer_handles_empty_current() {
        assert!(!is_newer(Some(""), Some("2.0.0")));
    }

    #[test]
    fn test_is_newer_handles_empty_latest() {
        assert!(!is_newer(Some("1.0.0"), Some("")));
    }

    #[test]
    fn test_is_newer_handles_both_empty() {
        assert!(!is_newer(None, None));
    }

    #[test]
    fn test_normalize_strips_v_prefix() {
        assert_eq!(normalize("v1.2.3"), "1.2.3");
    }

    #[test]
    fn test_normalize_strips_parenthetical() {
        assert_eq!(normalize("1.2.3 (beta)"), "1.2.3");
    }

    #[test]
    fn test_normalize_strips_space_suffix() {
        assert_eq!(normalize("1.2.3 build 42"), "1.2.3");
    }

    #[test]
    fn test_digits_only_keeps_numbers_and_dots() {
        assert_eq!(digits_only("1.2.3beta4"), "1.2.34");
    }

    #[test]
    fn test_is_newer_with_beta_versions() {
        assert!(is_newer(Some("1.0.0-beta"), Some("1.0.0")));
    }

    #[test]
    fn test_is_newer_with_complex_versions() {
        assert!(is_newer(Some("1.2"), Some("1.2.3")));
    }

    #[test]
    fn test_is_newer_digits_fallback_with_rc_suffixes() {
        // digits_only("1.0.0rc1") = "1.0.01", digits_only("2.0.0rc2") = "2.0.02"
        // Both parse as valid semver after digit stripping
        assert!(is_newer(Some("1.0.0rc1"), Some("2.0.0rc2")));
    }
}
