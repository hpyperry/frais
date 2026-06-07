// Frais CLI entry point.
// macOS-only CLI that scans for outdated software with LLM-powered version research.
// Matches Python's frais/cli.py main_entry().

use clap::Parser;
use std::process;

fn main() {
    // macOS-only guard — matches Python's platform.system() != "Darwin" check
    if std::env::consts::OS != "macos" {
        eprintln!("Error: Frais only runs on macOS.");
        process::exit(1);
    }

    // Handle --version / -v before clap (matches Python's pre-typer check)
    // This is needed because --json can appear with --version
    let args: Vec<String> = std::env::args().collect();
    let has_version = args.iter().any(|a| a == "--version" || a == "-v");
    if has_version {
        if args.iter().any(|a| a == "--json") {
            // Python: print_json_success(version=__version__)
            let version = env!("CARGO_PKG_VERSION");
            let json = format!(r#"{{"ok":true,"version":"{}"}}"#, version);
            println!("{}", json);
        } else {
            println!("frais {}", env!("CARGO_PKG_VERSION"));
        }
        process::exit(0);
    }

    let cli = frais_lib::cli::Cli::parse();

    // Initialize logging based on flags
    frais_lib::logging_config::configure(cli.debug, cli.log_file.as_deref(), cli.no_log);
    log::debug!("Frais {} starting", env!("CARGO_PKG_VERSION"));

    // Dispatch to subcommand handler
    if let Err(e) = frais_lib::cli::run(cli) {
        eprintln!("Error: {e}");
        process::exit(1);
    }
}
