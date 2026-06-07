// CLI module — matches Python's frais/cli.py.
// clap app definition and subcommand dispatch.

pub mod advise;
pub mod config;
pub mod doctor;
pub mod ignore;
pub mod output;
pub mod plugins_cmd;
pub mod scan;
pub mod scan_progress;
pub mod signal;
pub mod summarize;
pub mod update;

use clap::{Parser, Subcommand, Args};
use std::process;

/// Frais: macOS update checker with LLM-powered version research.
#[derive(Parser, Debug)]
#[command(name = "frais", version, about, long_about = None, disable_version_flag = true)]
pub struct Cli {
    /// Print detailed debug logs
    #[arg(long, global = true)]
    pub debug: bool,

    /// Override default log file path
    #[arg(long, global = true)]
    pub log_file: Option<String>,

    /// Disable file logging entirely
    #[arg(long, global = true)]
    pub no_log: bool,

    /// Show version and exit
    #[arg(short = 'v', long = "version", global = true)]
    pub show_version: bool,

    #[command(subcommand)]
    pub command: Option<Commands>,
}

#[derive(Subcommand, Debug)]
pub enum Commands {
    /// Check system status and configuration
    Doctor(DoctorArgs),

    /// Manage LLM provider configuration
    #[command(subcommand)]
    Config(ConfigCommands),

    /// Manage scanner plugins
    #[command(subcommand)]
    Plugins(PluginsCommands),

    /// Manage ignored application list
    #[command(subcommand)]
    Ignore(IgnoreCommands),

    /// Scan and generate LLM-powered update advice
    Advise(AdviseArgs),

    /// Scan for outdated software (no AI summaries)
    Scan(ScanArgs),

    /// Generate AI summary for a single item
    Summarize(SummarizeArgs),

    /// Interactively apply updates
    Update(UpdateArgs),
}

// ============================================================================
// Command argument structs
// ============================================================================

#[derive(Args, Debug)]
pub struct DoctorArgs {
    /// Output structured JSON
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct JsonFlag {
    /// Output structured JSON
    #[arg(long)]
    pub json: bool,
}

// Make JsonFlag's json field accessible
impl JsonFlag {
    pub fn json(&self) -> bool { self.json }
}

#[derive(Subcommand, Debug)]
pub enum ConfigCommands {
    /// Show current configuration
    Show(JsonFlag),
    /// Manage configuration interactively
    Manage,
    /// Show config file path
    Path(JsonFlag),
    /// Test LLM connection
    Test(JsonFlag),
}

#[derive(Subcommand, Debug)]
pub enum PluginsCommands {
    /// List all plugins and their status
    List(JsonFlag),
    /// Enable a plugin
    Enable(PluginAction),
    /// Disable a plugin
    Disable(PluginAction),
}

#[derive(Args, Debug)]
pub struct PluginAction {
    /// Plugin name
    pub name: String,
    /// Output structured JSON
    #[arg(long)]
    pub json: bool,
}

#[derive(Subcommand, Debug)]
pub enum IgnoreCommands {
    /// List ignored applications
    List(JsonFlag),
    /// Add an application to the ignore list
    Add(IgnoreAction),
    /// Remove an application from the ignore list
    Remove(IgnoreAction),
}

#[derive(Args, Debug)]
pub struct IgnoreAction {
    /// Application ID (bundle identifier)
    pub app_id: String,
    /// Output structured JSON
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct AdviseArgs {
    /// Output structured JSON
    #[arg(long)]
    pub json: bool,
    /// Comma-separated list of plugins to use
    #[arg(long, value_delimiter = ',')]
    pub plugins: Option<Vec<String>>,
    /// Maximum parallel research jobs (1-20)
    #[arg(short = 'j', long, default_value = "10")]
    pub jobs: usize,
    /// Show all items, including up-to-date
    #[arg(long)]
    pub all: bool,
}

#[derive(Args, Debug)]
pub struct ScanArgs {
    /// Output structured JSON
    #[arg(long)]
    pub json: bool,
    /// Comma-separated list of plugins to use
    #[arg(long, value_delimiter = ',')]
    pub plugins: Option<Vec<String>>,
    /// Show all items, including up-to-date
    #[arg(long)]
    pub all: bool,
    /// Maximum parallel research jobs (1-20)
    #[arg(short = 'j', long, default_value = "10")]
    pub jobs: usize,
}

#[derive(Args, Debug)]
pub struct SummarizeArgs {
    /// Item ID to summarize (from scan output)
    pub item_id: String,
    /// Output structured JSON
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct UpdateArgs {
    /// Filter by item ID or name
    pub only: Option<String>,
}

// ============================================================================
// Dispatch
// ============================================================================

/// Run a parsed CLI command. Returns Ok(()) on success, Err on failure.
pub fn run(cli: Cli) -> Result<(), String> {
    let command = cli.command.unwrap_or_else(|| {
        // No subcommand — show help (clap handles this with no_args_is_help equivalent)
        eprintln!("Run `frais --help` for available commands.");
        process::exit(0);
    });

    match command {
        Commands::Doctor(args) => doctor::run(args),
        Commands::Config(cmd) => match cmd {
            ConfigCommands::Show(args) => config::show(args),
            ConfigCommands::Manage => config::manage(),
            ConfigCommands::Path(args) => config::path(args),
            ConfigCommands::Test(args) => config::test(args),
        },
        Commands::Plugins(cmd) => match cmd {
            PluginsCommands::List(args) => plugins_cmd::list(args),
            PluginsCommands::Enable(args) => plugins_cmd::enable(args),
            PluginsCommands::Disable(args) => plugins_cmd::disable(args),
        },
        Commands::Ignore(cmd) => match cmd {
            IgnoreCommands::List(args) => ignore::list(args),
            IgnoreCommands::Add(args) => ignore::add(args),
            IgnoreCommands::Remove(args) => ignore::remove(args),
        },
        Commands::Advise(args) => advise::run(args),
        Commands::Scan(args) => scan::run(args),
        Commands::Summarize(args) => summarize::run(args),
        Commands::Update(args) => update::run(args),
    }
}
