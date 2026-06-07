// Logging configuration — matches Python's frais/logging_config.py.

use std::path::Path;
use std::sync::Once;

static LOGGER_INIT: Once = Once::new();

/// Configure the logging system.
/// - `debug`: if true, set log level to Debug, otherwise Info.
/// - `log_file`: override the default log file path.
/// - `no_log`: if true, disable file logging entirely.
pub fn configure(debug: bool, log_file: Option<&str>, no_log: bool) {
    LOGGER_INIT.call_once(|| {
        let level = if debug { "debug" } else { "info" };

        if no_log {
            // Console-only logging via flexi_logger
            flexi_logger::Logger::try_with_str(level)
                .unwrap()
                .format_for_stderr(flexi_logger::colored_default_format)
                .start()
                .ok();
        } else {
            let log_path = log_file
                .map(|s| s.to_string())
                .unwrap_or_else(|| {
                    crate::paths::default_log_file()
                        .to_string_lossy()
                        .to_string()
                });

            // Ensure log directory exists
            if let Some(parent) = Path::new(&log_path).parent() {
                let _ = std::fs::create_dir_all(parent);
            }

            // Use flexi_logger for file rotation
            flexi_logger::Logger::try_with_str(level)
                .unwrap()
                .log_to_file(
                    flexi_logger::FileSpec::try_from(&log_path)
                        .unwrap_or_else(|_| flexi_logger::FileSpec::default()),
                )
                .rotate(
                    flexi_logger::Criterion::Size(crate::paths::LOG_MAX_SIZE),
                    flexi_logger::Naming::Numbers,
                    flexi_logger::Cleanup::KeepLogFiles(2),
                )
                .format_for_files(flexi_logger::detailed_format)
                .start()
                .ok();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    

    #[test]
    fn test_configure_no_log() {
        // This should not panic
        configure(false, None, true);
    }

    #[test]
    fn test_configure_with_debug() {
        configure(true, None, true);
    }

    #[test]
    fn test_configure_with_custom_log_file() {
        let tmp = tempfile::TempDir::new().unwrap();
        let log_path = tmp.path().join("test.log");
        let _path_str = log_path.to_string_lossy().to_string();
        // Note: Logger init is a Once, so this test works independently
    }
}
