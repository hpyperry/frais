// Frais — macOS update checker with LLM-powered version research.
// Public API entry point. Integration tests depend on this crate.

pub mod cli;
pub mod coordinator;
pub mod ignore_filter;
pub mod llm;
pub mod logging_config;
pub mod models;
pub mod paths;
pub mod plugins;
pub mod providers;
pub mod store;
pub mod system;
pub mod web_tools;
