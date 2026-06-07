// Ignore list store — matches Python's frais/store/ignore_store.py.
// Reads/writes ~/.frais/config/ignore.txt (newline-separated IDs).

use std::collections::BTreeSet;
use std::path::Path;

/// Load ignored app IDs from file.
/// Returns empty set if file doesn't exist.
pub fn load_ignored(path: &Path) -> BTreeSet<String> {
    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return BTreeSet::new(),
    };

    content
        .lines()
        .map(|line| line.trim().to_string())
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
        .collect()
}

/// Initialize an empty ignore file if it doesn't exist.
pub fn init_ignored(path: &Path) -> Result<(), String> {
    if path.exists() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("Cannot create dir: {e}"))?;
    }
    // Create empty file
    std::fs::write(path, "# Frais ignore list — one bundle ID per line\n")
        .map_err(|e| format!("Cannot create ignore file: {e}"))?;
    Ok(())
}

/// Save ignored IDs to file atomically. Preserves the comment header.
const IGNORE_HEADER: &str = "# Frais ignore list — one bundle ID per line\n";

pub fn save_ignored(ids: &BTreeSet<String>, path: &Path) -> Result<(), String> {
    let mut sorted: Vec<&String> = ids.iter().collect();
    sorted.sort();

    let mut content = String::from(IGNORE_HEADER);
    for id in &sorted {
        content.push_str(id);
        content.push('\n');
    }

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("Cannot create dir: {e}"))?;
    }

    let tmp_path = path.with_extension("txt.tmp");
    std::fs::write(&tmp_path, &content).map_err(|e| format!("Cannot write ignore file: {e}"))?;
    std::fs::rename(&tmp_path, path).map_err(|e| format!("Cannot save ignore file: {e}"))?;

    Ok(())
}

/// Add an app ID to the ignore list. Returns true if added, false if already present.
pub fn add_ignored(app_id: &str, path: &Path) -> Result<bool, String> {
    let mut ids = load_ignored(path);
    if !ids.insert(app_id.to_string()) {
        return Ok(false); // already present
    }
    save_ignored(&ids, path)?;
    Ok(true)
}

/// Remove an app ID from the ignore list. Returns true if removed, false if not found.
pub fn remove_ignored(app_id: &str, path: &Path) -> Result<bool, String> {
    let mut ids = load_ignored(path);
    if !ids.remove(app_id) {
        return Ok(false); // not found
    }
    save_ignored(&ids, path)?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_load_ignored_empty_when_no_file() {
        let ids = load_ignored(Path::new("/nonexistent/ignore.txt"));
        assert!(ids.is_empty());
    }

    #[test]
    fn test_load_ignored_skips_comments_and_blanks() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("ignore.txt");
        std::fs::write(
            &path,
            "# comment\n\ncom.example.app\n\n# another comment\ncom.foo.bar\n",
        )
        .unwrap();

        let ids = load_ignored(&path);
        assert_eq!(ids.len(), 2);
        assert!(ids.contains("com.example.app"));
        assert!(ids.contains("com.foo.bar"));
    }

    #[test]
    fn test_add_ignored_new() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("ignore.txt");

        let added = add_ignored("com.example.app", &path).unwrap();
        assert!(added);

        let ids = load_ignored(&path);
        assert!(ids.contains("com.example.app"));
    }

    #[test]
    fn test_add_ignored_duplicate() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("ignore.txt");

        add_ignored("com.example.app", &path).unwrap();
        let added = add_ignored("com.example.app", &path).unwrap();
        assert!(!added);
    }

    #[test]
    fn test_remove_ignored_existing() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("ignore.txt");

        add_ignored("com.example.app", &path).unwrap();
        let removed = remove_ignored("com.example.app", &path).unwrap();
        assert!(removed);

        let ids = load_ignored(&path);
        assert!(!ids.contains("com.example.app"));
    }

    #[test]
    fn test_remove_ignored_not_found() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("ignore.txt");

        let removed = remove_ignored("com.nonexistent.app", &path).unwrap();
        assert!(!removed);
    }
}
