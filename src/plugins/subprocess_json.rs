// Subprocess JSON helper — matches Python's frais/plugins/subprocess_json.py.
// Runs a command and parses its stdout as JSON, with env isolation and timeout.

use std::process::Command;
use std::time::Duration;

/// Run a command and parse its stdout as JSON.
/// Clears DYLD_LIBRARY_PATH from the subprocess environment.
/// Matches Python's run_json() including subprocess.run(..., timeout=timeout).
pub fn run_json(
    cmd: &[&str],
    ok_codes: &[i32],
    timeout_secs: u64,
) -> Result<serde_json::Value, String> {
    if cmd.is_empty() {
        return Err("Empty command".into());
    }

    let mut command = Command::new(cmd[0]);
    if cmd.len() > 1 {
        command.args(&cmd[1..]);
    }

    // Clear DYLD_LIBRARY_PATH from subprocess environment (matches Python's env isolation)
    command.env_clear();
    for (key, value) in std::env::vars() {
        if key != "DYLD_LIBRARY_PATH" {
            command.env(&key, value);
        }
    }
    // Ensure PATH is available
    if !std::env::vars().any(|(k, _)| k == "PATH") {
        command.env(
            "PATH",
            "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
        );
    }

    command.stdout(std::process::Stdio::piped());
    command.stderr(std::process::Stdio::piped());

    let mut child = command
        .spawn()
        .map_err(|e| format!("Cannot execute {}: {e}", cmd[0]))?;

    // Wait with timeout — matches Python's subprocess.run(..., timeout=timeout)
    // Rust stable doesn't have wait_timeout, so we poll with try_wait()
    let timeout = Duration::from_secs(timeout_secs);
    let start = std::time::Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {
                if start.elapsed() >= timeout {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!("{} timed out after {}s", cmd[0], timeout_secs));
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("Cannot execute {}: {e}", cmd[0]));
            }
        }
    };

    let stdout = child
        .stdout
        .take()
        .map(|mut out| {
            let mut buf = Vec::new();
            std::io::Read::read_to_end(&mut out, &mut buf).unwrap_or(0);
            buf
        })
        .unwrap_or_default();
    let stderr = child
        .stderr
        .take()
        .map(|mut err| {
            let mut buf = Vec::new();
            std::io::Read::read_to_end(&mut err, &mut buf).unwrap_or(0);
            buf
        })
        .unwrap_or_default();
    let output = (status, stdout, stderr);

    let (status, stdout, stderr) = output;
    let exit_code = status.code().unwrap_or(-1);

    if !ok_codes.contains(&exit_code) && !ok_codes.is_empty() {
        let stderr_str = String::from_utf8_lossy(&stderr);
        return Err(format!(
            "{} exited with code {}: {}",
            cmd[0],
            exit_code,
            stderr_str.trim()
        ));
    }

    let stdout_str = String::from_utf8_lossy(&stdout);
    if stdout_str.trim().is_empty() {
        return Ok(serde_json::Value::Object(serde_json::Map::new()));
    }

    serde_json::from_str(&stdout_str)
        .map_err(|e| format!("Cannot parse {} output as JSON: {e}", cmd[0]))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_run_json_echo_json() {
        let result = run_json(&["echo", r#"{"key": "value"}"#], &[0], 10);
        assert!(result.is_ok());
        let val = result.unwrap();
        assert_eq!(val["key"], "value");
    }

    #[test]
    fn test_run_json_empty_command() {
        let result = run_json(&[], &[0], 10);
        assert!(result.is_err());
    }

    #[test]
    fn test_run_json_non_zero_exit() {
        // `ls /nonexistent` will fail
        let result = run_json(
            &["ls", "/nonexistent/path/that/does/not/exist"],
            &[0],
            10,
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_run_json_ok_codes_match() {
        // npm outdated exits with code 1 when there are outdated packages
        let result = run_json(&["sh", "-c", "echo '{\"ok\": true}' ; exit 1"], &[0, 1], 10);
        assert!(result.is_ok());
    }

    #[test]
    fn test_run_json_empty_stdout() {
        let result = run_json(&["sh", "-c", "exit 0"], &[0], 10);
        assert!(result.is_ok());
        let val = result.unwrap();
        assert!(val.as_object().map(|o| o.is_empty()).unwrap_or(false));
    }

    #[test]
    fn test_run_json_timeout() {
        // Sleep for 5 seconds with a 1 second timeout
        let result = run_json(&["sleep", "5"], &[0], 1);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("timed out"));
    }
}
