# advise 验证详情

**日期**: 2026-06-07
**状态**: ✅ pass（0 个新问题）

---

## 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `--json` | ✅ `bool = False` | ✅ `bool = False` | ✅ |
| `--plugins` | ✅ `str \| None` | ✅ `Option<String>` | ✅ |
| `--jobs` / `-j` | ✅ `int (1-20) = 10` | ✅ `usize (1-20) = 10` | ✅ |
| `--all` | ✅ `bool = False` | ✅ `bool = False` | ✅ |
| `--verbose` | ✅ `bool` | ✅ `bool` (via global) | ✅ |
| `--debug` | ✅ `bool` | ✅ `bool` (via global) | ✅ |

## 逻辑流程对比

| 步骤 | Python | Rust | 匹配? |
|------|--------|------|-------|
| 1. LLM 客户端 | `_try_get_llm_client()` — 失败则警告 | 同 | ✅ |
| 2. 插件选择 | `coordinator.select_plugins()` | 同 | ✅ |
| 3. 并行扫描 | `run_scan_phase()` + `ThreadPoolExecutor` | `run_scan()` + `thread::scope` | ✅ |
| 4. Ignore 过滤 | `apply_ignore_filter()` | 同 | ✅ |
| 5. 并行汇总 | `coordinator.run_summaries()` — `plugin.summarize()` | `run_summaries()` — `plugin.summarize()` | ✅ |
| 6. 缓存保存 | 原子写入 `last_advice.json` | 同 | ✅ |
| 7. JSON 输出 | `print_json_success(**result.to_dict())` | serde 序列化 | ✅ |
| 8. CLI 输出 | `_print_advise_result()` 含 Rich Markdown | 格式输出 (无 Markdown 渲染) | ⚠️ |

## JSON 输出对比

| 字段 | Python | Rust | 匹配? |
|------|--------|------|-------|
| Top-level keys | `ok, system, plugin_results` | 同 (含 `warnings`) | ✅ |
| Candidate 含 `ai_summary` | ✅ 已填充 | ✅ 已填充 | ✅ |
| Candidate 含 `release_notes` | ✅ (可能 `null`) | ✅ (可能 `null`) | ✅ |
| `warnings` 键 | LLM 未配置时存在 | 同 | ✅ |

### 错误处理

| 错误场景 | Python | Rust | 匹配? |
|---------|--------|------|-------|
| no_plugins_matched | `"No available plugins matched: {names}"` + `requested` | 同 | ✅ (已修复) |

## 已知差异

- ~~CLI 输出：Rust 无 Rich Markdown 渲染（`ai_summary` 显示为纯文本），Python 使用 `rich.markdown.Markdown`~~ **已修复 (2026-06-07)**: 使用 `termimad::MadSkin` 渲染 Markdown，支持粗体、代码块、列表、链接等。

## 结论

✅ **PASS** — JSON 输出、错误处理与 Python 完全一致。Markdown 渲染已通过 `termimad` 修复。
