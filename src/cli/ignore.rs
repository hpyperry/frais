// ignore commands — matches Python's frais/commands/ignore.py.
use super::{IgnoreAction, JsonFlag};
use std::collections::BTreeMap;

pub fn list(args: JsonFlag) -> Result<(), String> {
    let ignored = crate::store::ignore_store::load_ignored(&crate::paths::ignore_path());

    if args.json() {
        let list: Vec<_> = ignored
            .iter()
            .map(|s| serde_json::Value::String(s.clone()))
            .collect();
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("ignored".into(), serde_json::Value::Array(list));
        extra.insert(
            "count".into(),
            serde_json::Value::Number((ignored.len() as u64).into()),
        );
        super::output::print_json_success(extra);
    } else {
        if ignored.is_empty() {
            println!("  {}", super::output::dim("No ignored apps."));
        } else {
            println!(
                "{} {}",
                super::output::label("Ignored:"),
                super::output::dim(format!("{} app(s)", ignored.len()))
            );
            for id in &ignored {
                println!("  {}", id);
            }
        }
    }
    Ok(())
}

pub fn add(args: IgnoreAction) -> Result<(), String> {
    let added = crate::store::ignore_store::add_ignored(&args.app_id, &crate::paths::ignore_path())
        .map_err(|e| format!("Cannot update ignore list: {e}"))?;

    let action = if added { "added" } else { "already_ignored" };

    if args.json {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("app_id".into(), args.app_id.clone().into());
        extra.insert("action".into(), action.into());
        super::output::print_json_success(extra);
    } else {
        if added {
            println!(
                "{}",
                super::output::success(format!("Added: {}", args.app_id))
            );
        } else {
            println!(
                "{}",
                super::output::dim(format!("Already ignored: {}", args.app_id))
            );
        }
    }
    Ok(())
}

pub fn remove(args: IgnoreAction) -> Result<(), String> {
    let removed =
        crate::store::ignore_store::remove_ignored(&args.app_id, &crate::paths::ignore_path())
            .map_err(|e| format!("Cannot update ignore list: {e}"))?;

    let action = if removed { "removed" } else { "not_in_list" };

    if args.json {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("app_id".into(), args.app_id.clone().into());
        extra.insert("action".into(), action.into());
        super::output::print_json_success(extra);
    } else {
        if removed {
            println!(
                "{}",
                super::output::success(format!("Removed: {}", args.app_id))
            );
        } else {
            println!(
                "{}",
                super::output::warning(format!("Not in ignore list: {}", args.app_id))
            );
        }
    }
    Ok(())
}
