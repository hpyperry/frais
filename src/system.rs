// System detection — matches Python's frais/system.py.

use crate::models::SystemProfile;

/// Detect the current system profile.
/// On macOS, uses platform info and standard Applications paths.
pub fn detect_system() -> SystemProfile {
    let os_name = if cfg!(target_os = "macos") {
        "macOS".to_string()
    } else {
        std::env::consts::OS.to_string()
    };

    let os_version = if cfg!(target_os = "macos") {
        macos_version()
    } else {
        "Unknown".to_string()
    };

    // Use uname -m to match Python's platform.machine()
    // (std::env::consts::ARCH returns "aarch64" on Apple Silicon,
    // but platform.machine() returns "arm64")
    let arch = if cfg!(target_os = "macos") {
        macos_arch()
    } else {
        std::env::consts::ARCH.to_string()
    };

    // Standard Applications directories on macOS
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    let applications_paths = vec![
        "/Applications".to_string(),
        format!("{}/Applications", home),
    ];

    SystemProfile {
        os_name,
        os_version,
        arch,
        applications_paths,
    }
}

/// Get macOS architecture via uname -m (matches Python's platform.machine()).
fn macos_arch() -> String {
    if let Ok(output) = std::process::Command::new("uname")
        .arg("-m")
        .output()
    {
        if output.status.success() {
            let arch = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !arch.is_empty() {
                return arch;
            }
        }
    }
    // Fallback to compile-time arch
    std::env::consts::ARCH.to_string()
}

/// Get macOS version string via sysctl.
fn macos_version() -> String {
    // Try sysctl kern.osproductversion (most reliable for macOS version)
    if let Ok(output) = std::process::Command::new("sysctl")
        .args(["-n", "kern.osproductversion"])
        .output()
    {
        if output.status.success() {
            let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !version.is_empty() {
                return version;
            }
        }
    }
    // Fallback: try sw_vers
    if let Ok(output) = std::process::Command::new("sw_vers")
        .arg("-productVersion")
        .output()
    {
        if output.status.success() {
            let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !version.is_empty() {
                return version;
            }
        }
    }
    "Unknown".to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_system_returns_valid_profile() {
        let profile = detect_system();
        assert!(!profile.os_name.is_empty());
        assert!(!profile.arch.is_empty());
        assert!(!profile.applications_paths.is_empty());
        assert!(profile.applications_paths.contains(&"/Applications".to_string()));
    }

    #[test]
    fn test_detect_system_on_macos() {
        if cfg!(target_os = "macos") {
            let profile = detect_system();
            assert_eq!(profile.os_name, "macOS");
        }
    }
}
