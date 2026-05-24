# Logging Fix Plan

## Goal

Make Frais logging satisfy two requirements:

- Comply with `python_engineering_spec_strict.md`, especially the structured logging requirement.
- Provide enough context to debug concurrent scans, LLM research, web fetches, plugin failures, and user-machine bug reports.

This plan does not change user-facing command output or the existing JSON command contract.

## Current Assessment

The current logging system is usable for day-to-day debugging, but it is not sufficient for robust incident reconstruction:

- Logging is centralized and CLI flags are clear.
- stderr and file logging are separated correctly.
- LLM, web, subprocess, and plugin failure paths have useful log points.
- However, logs are plain text rather than structured records.
- Concurrent application research lacks stable correlation fields.
- Debug logs can contain large prompt, response, search, and fetched-content previews.
- Scan lifecycle logs are incomplete.
- Large log files are truncated by clearing the file, which can lose recent context.

## Scope

Expected files to touch:

- `src/frais/logging_config.py`
- `src/frais/cli.py`
- `src/frais/coordinator.py`
- `src/frais/plugins/applications/plugin.py`
- `src/frais/plugins/applications/research/pipeline.py`
- `src/frais/plugins/homebrew/plugin.py`
- `src/frais/plugins/npm/plugin.py`
- `src/frais/web_tools.py`
- `src/frais/llm/_openai_compatible.py`
- `tests/integration/cli/test_cli.py`
- `tests/unit/test_logging_config.py`
- `README.md`
- `AGENTS.md`

## Plan

### 1. Improve Logging Infrastructure

- Keep the standard `logging` module to minimize migration risk.
- Add a JSON formatter for file logs.
- Preserve the existing CLI behavior:
  - default stderr level remains `ERROR`
  - `--verbose` maps to `INFO`
  - `--debug` maps to `DEBUG`
  - `--log-file` overrides the default file path
  - `--no-log` disables file logging
- Include the following baseline fields in every structured file log:
  - `timestamp`
  - `level`
  - `logger`
  - `module`
  - `function`
  - `line`
  - `message`
  - `run_id`

### 2. Add Runtime Context

- Generate a `run_id` once in the CLI callback.
- Inject runtime context through `contextvars` and a logging filter.
- Avoid mutable business-level global state.
- Add stable contextual fields where available:
  - `command`
  - `plugin`
  - `item_id`
  - `item_name`
  - `step`
  - `duration_ms`
  - `candidate_count`
  - `skipped_count`

### 3. Add Scan Lifecycle Logs

- Add lifecycle logs in `coordinator.run_scan()`:
  - scan started
  - plugin scan started
  - plugin scan completed
  - plugin scan failed
- Add lifecycle logs in `coordinator.run_summaries()`:
  - summaries started
  - summary completed
  - summary failed
  - summaries completed
- Include elapsed duration and candidate/skipped counts where possible.

### 4. Improve Plugin Logs

- Applications plugin:
  - log application discovery count
  - log research queue size
  - log per-item research failure with `item_id` and `item_name`
  - log final candidate count
- Homebrew plugin:
  - log scan start and completion
  - log subprocess failures with command context
  - log outdated/installed/candidate counts
- npm plugin:
  - log scan start and completion
  - log subprocess failures with command context
  - log outdated/installed/candidate counts

### 5. Improve LLM and Web Trace Safety

- Keep debug trace support, but make it bounded and explicit.
- Do not log:
  - API keys
  - authorization headers
  - full prompt bodies
  - full model responses
  - full fetched web pages
- Log safe metadata instead:
  - provider URL
  - model
  - message count
  - payload preview length
  - response preview length
  - token usage
  - fetched URL
  - response character count
  - truncated preview only in `DEBUG`
- Keep previews short and centralized through helper functions.

### 6. Make Research Failures More Diagnosable

- Preserve the current tolerant behavior where one failed app does not abort the whole scan.
- Add structured warning logs for each research stage failure:
  - `generate_search_queries`
  - `web_search`
  - `pick_urls`
  - `web_fetch`
  - `extract_version`
- Add concise skipped reasons where this helps explain missing candidates.
- Avoid flooding the final user output with low-level diagnostics.

### 7. Replace Clear-On-Size With Log Rotation

- Replace direct file clearing with `RotatingFileHandler`.
- Keep the default maximum size at the current project limit.
- Preserve a small number of backups, likely 1 to 3 files.
- Keep `error.log` as a separate error-only file.

### 8. Update Tests

Add or update tests for:

- default stderr level is still `ERROR`
- `--verbose` sets stderr to `INFO`
- `--debug` sets stderr to `DEBUG`
- `--no-log` does not create log files
- file logs are valid JSON Lines
- structured file logs include `run_id`
- structured file logs include custom fields from `extra`
- API keys are not present in logs
- plugin lifecycle logs include plugin name, duration, candidate count, and skipped count
- log rotation creates backup files instead of clearing context

Tests should continue using `monkeypatch` for external effects. No real network, real Homebrew, or real npm calls should be required.

### 9. Update Documentation

Update `README.md` Logs section:

- document JSON Lines file logs
- document stderr behavior
- document default log paths
- document `error.log`
- document rotation behavior
- clarify that `--debug` records bounded LLM and web trace previews

Update `AGENTS.md` Logging section:

- reflect the structured logging implementation
- describe required contextual fields for future changes
- document redaction requirements

### 10. Verify

Run the following checks:

```bash
uv run pytest
uv run frais --debug doctor
uv run --extra build python scripts/build_binary.py
```

If the binary build succeeds, run a lightweight command through the built artifact to verify logging works outside the source tree.

## Acceptance Criteria

- File logs are structured JSON Lines.
- stderr logging remains human-readable and does not break JSON command output.
- Every command run has a `run_id`.
- Plugin scan start/end/failure events are visible in logs.
- Summary start/end/failure events are visible in logs.
- LLM and web debug logs are bounded and do not expose credentials.
- Log rotation preserves recent context instead of clearing the active file.
- Tests cover the changed behavior.
- README and AGENTS logging documentation match implementation.
