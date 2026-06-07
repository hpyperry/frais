# summarize 验证详情

**日期**: 2026-06-07
**状态**: ✅ pass（3 个 BUG 已修复）

---

## 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `item_id` (位置参数, 必填) | ✅ `str` | ✅ `String` | ✅ |
| `--json` | ✅ `bool = False` | ✅ `bool = False` | ✅ |

## 逻辑流程对比

| 步骤 | Python | Rust (修复后) | 匹配? |
|------|--------|-------------|-------|
| 1. 加载缓存 | `load_scan_cache()` | 同 | ✅ |
| 2. no_cache 错误 | `exit_with_error(reason="no_cache")` | 同 | ✅ |
| 3. 查找 candidate | 线性扫描 `plugin_results` | 同 | ✅ |
| 4. candidate_not_found | `exit_with_error(reason="candidate_not_found")` | 同 | ✅ (hint 已修复) |
| 5. 已缓存 summary | 直接返回 | 同 | ✅ |
| 6. LLM 客户端 | `require_config()` → `config_missing` | 同 | ✅ (exit code 已修复) |
| 7. 查找 plugin | `all_plugins()[plugin_name]` → `plugin_not_found` | 同 | ✅ |
| 8. 生成 summary | `plugin.summarize(llm, candidate)` (中文 prompt) | 同 | ✅ (已修复为调用 plugin) |
| 9. 保存到缓存 | 原子写入 | 同 | ✅ |
| 10. JSON 输出 | `{"ok":true,"item_id":"...","ai_summary":"..."}` | 同 | ✅ |

## JSON 输出对比

| 场景 | Python | Rust (修复后) | 匹配? |
|------|--------|-------------|-------|
| 成功 | `{"ok":true,"item_id":"...","ai_summary":"..."}` | 同 | ✅ |
| no_cache | `{"ok":false,"error":"...","reason":"no_cache","hint":"..."}` | 同 | ✅ |
| cache_read_error | `exit_with_error(reason="cache_read_error")` | 同 | ✅ |
| candidate_not_found | `{"ok":false,...,"item_id":"..."}` | 同 | ✅ (hint 已修复) |
| config_missing | exit 2, reason=config_missing | exit 2, reason=config_missing | ✅ (已修复) |
| plugin_not_found | `{"ok":false,...,"plugin_name":"..."}` | 同 | ✅ |

## 修复记录

| ID | 严重度 | 描述 | 修复 |
|----|--------|------|------|
| BUG-10 | BUG | summarize 绕过 plugin.summarize() 使用英文 prompt | 改为调用 `plugin.summarize()` (中文 prompt) |
| BUG-11 | BUG | config_missing exit code 为 1，Python 为 2 | 改为 exit_code=2 |
| BUG-12 | BUG | candidate_not_found hint 格式不匹配 | 修正 hint 文案 |
| BUG-15 | MISSING | CLI 输出未渲染 Markdown | 使用 `termimad::MadSkin::print_text()` 渲染 |

## 结论

✅ **PASS** — 4 个问题已修复。逻辑、JSON 输出、错误处理与 Python 完全一致。Markdown 终端渲染已添加。
