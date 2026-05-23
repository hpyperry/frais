# Frais Architecture Refactor Plan

This plan tracks the remaining architecture cleanup work after the first refactor pass.
The goal is to keep Frais' current plugin-oriented design while making module ownership
match `python_engineering_spec_strict.md`.

## Goals

- Keep `cli.py` as command registration only.
- Keep behavior and JSON output contracts stable.
- Prefer concrete module names over generic names such as `utils`, `manager`, or `core`.
- Keep functions under the strict line limits where practical.
- Add tests with each structural change.

## Phase 1: Plugin Package Split

Move plugin implementation out of package `__init__.py` files.

Target structure:

```text
src/frais/plugins/
  applications/
    __init__.py          # re-export only
    plugin.py            # ApplicationsPlugin
    discovery.py         # scan_applications, read_application
    source_classifier.py # classify_source, signing/quarantine helpers
    app_store.py         # rename current _store.py
  homebrew/
    __init__.py          # re-export only
    plugin.py            # HomebrewPlugin
  npm/
    __init__.py          # re-export only
    plugin.py            # NpmPlugin
```

Required updates:

- Update entry points in `pyproject.toml`.
- Update imports in tests.
- Preserve public imports from `frais.plugins.applications`, `frais.plugins.homebrew`, and `frais.plugins.npm`.

Validation:

```bash
uv run pytest tests/test_applications.py tests/test_homebrew.py tests/test_npm.py
```

## Phase 2: Applications Research Split

Split `plugins/applications/_research.py` by responsibility.

Target structure:

```text
src/frais/plugins/applications/research/
  __init__.py
  pipeline.py           # research_application_update, structured research flow
  prompts.py            # LLM prompt constants
  json_parser.py        # extract/parse JSON helpers
  candidate_factory.py  # UpdateCandidate construction
  version_compare.py    # version normalization and comparison
```

Important constraints:

- Keep the 3-step LLM pipeline unchanged: generate queries -> pick URLs -> extract version.
- Keep App Store fast path behavior unchanged.
- Keep evidence, risk level, and recommended action output compatible with current tests.
- Avoid broad `except Exception` where a narrower exception type is available.

Validation:

```bash
uv run pytest tests/test_research.py tests/test_applications.py
```

## Phase 3: Command Function Shrink

Break long command functions into narrow helpers without changing CLI behavior.

Targets:

- `commands/advise.py`
  - Split config loading, plugin selection, scan phase, summary phase, and output/cache writing.
- `commands/scan.py`
  - Split plugin selection and interrupt handling.
- `commands/summarize.py`
  - Split cache read, candidate lookup, summary generation, and cache update.
- `commands/update.py`
  - Split cache read, candidate parsing, filtering, rendering, and execution.
- `commands/_scan_core.py`
  - Move Rich progress rendering into `ui/scan_progress.py`.

Proposed additions:

```text
src/frais/ui/
  __init__.py
  scan_progress.py
```

Validation:

```bash
uv run pytest tests/test_cli.py tests/test_commands.py
```

## Phase 4: Type Strictness

Add static typing enforcement after the structural modules are stable.

`pyproject.toml` additions:

```toml
[tool.mypy]
strict = true
python_version = "3.11"

[tool.ruff]
target-version = "py311"
line-length = 100
```

Expected fixes:

- Replace remaining untyped helper parameters in command modules.
- Replace loose `dict`/`tuple` returns with typed dataclasses where useful.
- Reduce `Any` usage to external JSON boundaries.
- Add typed wrappers for Homebrew and npm JSON payload parsing where practical.

Validation:

```bash
uv run mypy src
uv run ruff check src tests
uv run pytest
```

## Phase 5: Test Layout Cleanup

Move tests toward the structure required by the strict engineering spec.

Target structure:

```text
tests/
  unit/
    commands/
    plugins/
    store/
    llm/
  integration/
    cli/
```

Guidelines:

- Move tests incrementally with the module they cover.
- Rename coverage-only tests to describe behavior, not coverage.
- Keep monkeypatch-based external dependency isolation.

## Phase 6: Final Verification

Run the full local release verification after each phase that changes imports or CLI behavior.

```bash
uv run pytest
uv run --extra build python scripts/build_binary.py
./dist/frais doctor --json
```

## Recommended PR Order

1. Plugin package split.
2. Applications research split.
3. Command function shrink and `ui/scan_progress.py`.
4. Type strictness and lint configuration.
5. Test layout cleanup.

Each PR should update `README.md`, `CLAUDE.md`, and `AGENTS.md` if public structure or workflow changes.
