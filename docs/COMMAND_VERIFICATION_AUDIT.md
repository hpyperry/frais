# Command Verification Audit

**日期**: 2026-06-07
**分支**: `rust-rewrite`
**范围**: 全部 Frais CLI 命令 — Python (`src/frais/`) vs Rust (`src/`)

---

## Master Status Table

| # | Command | Status | Issues Fixed | Last Verified |
|---|---------|--------|-------------|---------------|
| 1 | `--version` / `-v` | ✅ pass | 0 | 2026-06-07 |
| 2 | `doctor` | ✅ pass | 2 BUG | 2026-06-07 |
| 3 | `config path` | ✅ pass | 0 | 2026-06-07 |
| 4 | `config show` | ✅ pass | 1 COS | 2026-06-07 |
| 5 | `config test` | ✅ pass | 3 BUG + 1 COS | 2026-06-07 |
| 6 | `config manage` | ✅ pass | 0 | 2026-06-07 |
| 7 | `plugins list` | ✅ pass | 0 | 2026-06-07 |
| 8 | `plugins enable/disable` | ✅ pass | 2 BUG | 2026-06-07 |
| 9 | `ignore list` | ✅ pass | 2 COS | 2026-06-07 |
| 10 | `ignore add/remove` | ✅ pass | 2 COS | 2026-06-07 |
| 11 | `scan` | ✅ pass | 3 BUG | 2026-06-07 |
| 12 | `advise` | ✅ pass | 1 MISSING | 2026-06-07 |
| 13 | `summarize` | ✅ pass | 5 BUG | 2026-06-07 |
| 14 | `update` | ✅ pass | 1 MISSING | 2026-06-07 |

**总结**: 14/14 命令全部通过 ✅

---

## All Resolved Issues (17 total)

### Phase 1: Command verification (round 1)

| ID | Command | Severity | Description |
|----|---------|----------|-------------|
| BUG-01 | doctor | BUG | `system.arch` 返回 `aarch64` 而非 `arm64` |
| BUG-02 | doctor | BUG | `llm.provider` JSON 返回 `deepseek` (ID) 而非 `DeepSeek` (名称) |
| BUG-03 | plugins | BUG | enable/disable 错误 JSON 缺少 `plugin_name` 上下文 |
| BUG-04 | plugins | BUG | hint 文案不匹配 Python |
| BUG-05 | config test | BUG | JSON `provider` 返回 ID 而非显示名称 |
| BUG-06 | config test | BUG | connection_error exit code = 1 应为 2 |
| BUG-07 | config test | BUG | hint 文案缺少 "then try again." |
| BUG-08 | scan | BUG | Candidate JSON 缺少 `release_notes` / `ai_summary` (serde skip) |
| BUG-09 | scan/advise | BUG | no_plugins_matched error 消息格式不匹配 |
| BUG-10 | summarize | BUG | 绕过 plugin.summarize() 使用英文 prompt |
| BUG-11 | summarize | BUG | config_missing exit code = 1 应为 2 |
| BUG-12 | summarize | BUG | candidate_not_found hint 文案不匹配 |
| COS-01 | config show | COSMETIC | CLI Provider 显示 ID 而非显示名称 |
| COS-02—04 | ignore | COSMETIC | list/add/remove 文案不匹配 Python |
| COS-05 | config test | COSMETIC | CLI 输出格式不匹配 |

### Phase 2: Feature completeness (round 2)

| ID | Command | Severity | Description |
|----|---------|----------|-------------|
| BUG-13 | advise, update, summarize | MISSING | Markdown 终端渲染 — 添加 `termimad` crate，使用 `MadSkin::print_text()` |
| BUG-14 | applications plugin | BUG | App Store 应用被排除在 research 之外 — 移除 `SourceKind::AppStore` 过滤器，所有 items 通过 iTunes API / LLM 双通道研究 |
| BUG-15 | summarize | BUG | `build_summary_prompt()` 只传依赖数量不传名称 — 现在传 `Depends on: N (name1, name2)` |

**总计**: 14 BUG + 5 COSMETIC + 2 MISSING 全部已修复

---

## Rust 相比 Python 的改进

| 改进 | 说明 |
|------|------|
| App Store 版本检查 | Python 将 App Store 应用排除在 research 之外，永远不会获得版本检查。Rust 通过 iTunes API 快速通道检查所有 App Store 应用 |
| 依赖名称提示 | `summarize` prompt 包含具体依赖名称（如 `readline`, `python@3.14`），Python 只传数量 |
| `FRAIS_HOME` env var | Rust 新增，支持自定义数据目录 |
| Markdown 渲染 | `termimad` 提供与 Python `rich.markdown` 同等的终端 Markdown 渲染 |

---

## Known Acceptable Differences

| 差异 | 影响 | 理由 |
|------|------|------|
| CLI Rich Table vs console 格式 (doctor, config, plugins) | 低 | 信息内容等价 |
| JSON 字段排序 (BTreeMap alphabetical vs insertion) | 无 | JSON 对象键无序 |
| Python 测试已移除 | — | Rust 有 24 个集成测试覆盖相同场景 |

---

## 文件结构

```
docs/
├── COMMAND_VERIFICATION_AUDIT.md   ← 本文件 (总览)
└── command-details/
    ├── version.md                    ← --version 详情
    ├── doctor.md                     ← doctor 详情
    ├── config-path-show.md           ← config path + show 详情
    ├── config-test-manage.md         ← config test + manage 详情
    ├── plugins.md                    ← plugins 详情
    ├── ignore.md                     ← ignore 详情
    ├── scan.md                       ← scan 详情
    ├── advise.md                     ← advise 详情
    ├── summarize.md                  ← summarize 详情
    └── update.md                     ← update 详情
```
