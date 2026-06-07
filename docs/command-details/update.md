# update 验证详情

**日期**: 2026-06-07
**状态**: ✅ pass（0 个新问题）

---

## 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `ID_OR_NAME` (位置参数, 可选) | ✅ `str \| None` | ✅ `Option<String>` | ✅ |

交互式命令，不支持 `--json`。

## 逻辑流程对比

| 步骤 | Python (`update.py`) | Rust (`update.rs`) | 匹配? |
|------|---------------------|-------------------|-------|
| 1. 加载缓存 | `_load_advice_cache_or_exit()` → Exit(1) 如果缺失 | 同 | ✅ |
| 2. 解析 candidates | `_parse_candidates_from_cache()` — 从 `plugin_results` 键构建 `plugin_map` | 同 — `parse_candidates_from_cache()` 从缓存构建映射 | ✅ |
| 3. 过滤 | `_filter_candidates()` — **精确匹配** `c.item.id == only or c.item.name == only` | 同 — `c.item.id == filter \|\| c.item.name == filter` | ✅ |
| 4. 执行循环 | `_execute_update_loop()`: 显示 → 确认 → plugin.update() | 同 | ✅ |
| 5. 插件查找 | `plugin_map.get(candidate.item.id)` (从缓存) | 同 — `plugin_map.get(&candidate.item.id)` | ✅ |
| 6. App Store 更新 | 打开 `macappstore://` URL | 同 | ✅ |
| 7. 非自动更新 | `typer.confirm("Open app for manual update?")` → `open` 命令 | `dialoguer::Confirm` → `Command::new("open")` | ✅ |
| 8. 空结果 | "No update candidates found." (不是 error) | 同 | ✅ |

## 关键差异检查

| 审计项 | 审计结论 | 实际状态 |
|--------|---------|---------|
| #15 插件匹配 (SourceKind 猜测) | UNAUTHORIZED | ✅ **已修复** — 从缓存构建 `plugin_map` |
| #16 过滤逻辑 (子串匹配) | UNAUTHORIZED | ✅ **已修复** — 精确匹配 `==` |
| #17 Markdown 渲染 | MISSING | ✅ **已修复 (2026-06-07)** — 使用 `termimad::MadSkin` 渲染 |

## 结论

✅ **PASS** — 逻辑流程与 Python 完全一致。Markdown 渲染已通过 `termimad` 修复。
