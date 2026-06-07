// Integration tests for CLI commands using assert_cmd.
// All tests use FRAIS_HOME set to a temp directory to avoid
// touching the user's real ~/.frais/ configuration.
use assert_cmd::Command;
use predicates::prelude::*;

/// Helper to get the frais binary path with FRAIS_HOME set to a temp dir.
fn frais_in(tmp: &tempfile::TempDir) -> Command {
    let mut cmd = Command::cargo_bin("frais").unwrap();
    cmd.env("FRAIS_HOME", tmp.path().to_string_lossy().to_string());
    cmd
}

// ============================================================================
// Version
// ============================================================================

#[test]
fn test_version_flag() {
    let tmp = tempfile::TempDir::new().unwrap();
    frais_in(&tmp)
        .arg("--version")
        .assert()
        .success()
        .stdout(predicate::str::starts_with("frais "));
}

#[test]
fn test_version_short_flag() {
    let tmp = tempfile::TempDir::new().unwrap();
    frais_in(&tmp)
        .arg("-v")
        .assert()
        .success()
        .stdout(predicate::str::starts_with("frais "));
}

// ============================================================================
// Doctor
// ============================================================================

#[test]
fn test_doctor_output() {
    let tmp = tempfile::TempDir::new().unwrap();
    frais_in(&tmp)
        .arg("doctor")
        .assert()
        .success()
        .stdout(predicate::str::contains("Frais v"))
        .stdout(predicate::str::contains("OS:"))
        .stdout(predicate::str::contains("Arch:"))
        .stdout(predicate::str::contains("Plugins:"));
}

#[test]
fn test_doctor_json_output() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("doctor")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], true);
    assert!(json["version"].is_string());
    assert!(json["system"]["os_name"].is_string());
    assert!(json["system"]["arch"].is_string());
    assert!(json["plugins"].is_object());
}

// ============================================================================
// Config
// ============================================================================

#[test]
fn test_config_path() {
    let tmp = tempfile::TempDir::new().unwrap();
    frais_in(&tmp)
        .arg("config")
        .arg("path")
        .assert()
        .success()
        .stdout(predicate::str::contains("config.toml"));
}

#[test]
fn test_config_path_json() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("config")
        .arg("path")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], true);
    assert!(json["path"].as_str().unwrap().contains("config.toml"));
}

#[test]
fn test_config_show_not_configured() {
    let tmp = tempfile::TempDir::new().unwrap();
    frais_in(&tmp)
        .arg("config")
        .arg("show")
        .assert()
        .success()
        .stdout(predicate::str::contains("Not configured"));
}

#[test]
fn test_config_show_json() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("config")
        .arg("show")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], true);
    assert_eq!(json["configured"], false); // No config in temp dir
}

#[test]
fn test_config_test_no_config() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("config")
        .arg("test")
        .arg("--json")
        .assert()
        .code(2); // Exit code 2 for config/parameter errors

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], false);
    assert_eq!(json["reason"], "config_missing");
}

// ============================================================================
// Plugins
// ============================================================================

#[test]
fn test_plugins_list() {
    let tmp = tempfile::TempDir::new().unwrap();
    frais_in(&tmp)
        .arg("plugins")
        .arg("list")
        .assert()
        .success()
        .stdout(predicate::str::contains("applications"));
}

#[test]
fn test_plugins_list_json() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("plugins")
        .arg("list")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], true);
    let plugins = json["plugins"].as_array().unwrap();
    assert!(plugins.len() >= 2, "expected at least 2 built-in plugins");
}

#[test]
fn test_plugins_enable_unknown() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("plugins")
        .arg("enable")
        .arg("nonexistent")
        .arg("--json")
        .assert()
        .code(1);

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], false);
    assert_eq!(json["reason"], "unknown_plugin");
}

#[test]
fn test_plugins_disable_unknown() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("plugins")
        .arg("disable")
        .arg("nonexistent")
        .arg("--json")
        .assert()
        .code(1);

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], false);
    assert_eq!(json["reason"], "unknown_plugin");
}

// ============================================================================
// Ignore
// ============================================================================

#[test]
fn test_ignore_list_empty() {
    let tmp = tempfile::TempDir::new().unwrap();
    frais_in(&tmp)
        .arg("ignore")
        .arg("list")
        .assert()
        .success()
        .stdout(predicate::str::contains("No ignored"));
}

#[test]
fn test_ignore_list_json() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("ignore")
        .arg("list")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], true);
    assert_eq!(json["count"], 0);
}

#[test]
fn test_ignore_add_and_remove() {
    let tmp = tempfile::TempDir::new().unwrap();

    // Add
    let output = frais_in(&tmp)
        .arg("ignore")
        .arg("add")
        .arg("com.example.test")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], true);
    assert_eq!(json["action"], "added");

    // List should contain it
    let output = frais_in(&tmp)
        .arg("ignore")
        .arg("list")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["count"], 1);

    // Remove
    let output = frais_in(&tmp)
        .arg("ignore")
        .arg("remove")
        .arg("com.example.test")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], true);
    assert_eq!(json["action"], "removed");
}

// ============================================================================
// Scan
// ============================================================================

#[test]
fn test_scan_json_output() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("scan")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], true);
    assert!(json["system"].is_object());
    assert!(json["plugin_results"].is_object());
}

// ============================================================================
// Summarize
// ============================================================================

#[test]
fn test_summarize_no_cache() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("summarize")
        .arg("com.test.nonexistent")
        .arg("--json")
        .assert()
        .code(1);

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], false);
    assert_eq!(json["reason"], "no_cache");
}

// ============================================================================
// Update
// ============================================================================

#[test]
fn test_update_no_cache() {
    let tmp = tempfile::TempDir::new().unwrap();
    frais_in(&tmp)
        .arg("update")
        .assert()
        .code(1);
}

// ============================================================================
// Advise
// ============================================================================

#[test]
fn test_advise_json_output() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("advise")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], true);
    assert!(json["system"].is_object());
    assert!(json["plugin_results"].is_object());
}

// ============================================================================
// JSON format invariants (cross-command)
// ============================================================================

#[test]
fn test_json_envelope_ok_is_first_key() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("doctor")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let ok_pos = stdout.find("\"ok\"").unwrap();
    let version_pos = stdout.find("\"version\"").unwrap();
    assert!(ok_pos < version_pos, "\"ok\" should be the first key in JSON output");
}

#[test]
fn test_json_error_has_reason_and_hint() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("plugins")
        .arg("enable")
        .arg("nonexistent")
        .arg("--json")
        .assert()
        .code(1);

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    assert_eq!(json["ok"], false);
    assert!(json["error"].is_string(), "error field should be a string");
    assert!(json["reason"].is_string(), "reason field should be a string");
    assert!(json["hint"].is_string(), "hint field should be a string");
}

#[test]
fn test_json_output_is_valid_utf8() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("doctor")
        .arg("--json")
        .assert()
        .success();

    let stdout = output.get_output().stdout.clone();
    // Must be valid UTF-8 and parse as JSON
    let _: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
}

// ============================================================================
// Scanner plugin integration
// ============================================================================

#[test]
fn test_scan_includes_available_plugins() {
    let tmp = tempfile::TempDir::new().unwrap();
    let output = frais_in(&tmp)
        .arg("scan")
        .arg("--json")
        .assert()
        .success();

    let stdout = String::from_utf8(output.get_output().stdout.clone()).unwrap();
    let json: serde_json::Value = serde_json::from_str(&stdout).unwrap();
    let results = json["plugin_results"].as_object().unwrap();

    // Applications plugin should always be present (is_available = true)
    assert!(results.contains_key("applications"),
        "applications plugin should be in scan results");
}
