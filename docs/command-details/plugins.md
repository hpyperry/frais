# plugins 验证详情

**日期**: 2026-06-07
**状态**: ✅ pass（2 个 BUG 已修复）

---

## plugins list

### 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `--json` | ✅ `bool = False` | ✅ `bool = False` | ✅ |

### JSON 输出对比

| 字段 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `ok` | `true` (第一 key) | `true` (第一 key) | ✅ |
| `plugins` | `[{name, available, default, effective}]` | 同结构 | ✅ |
| 每个元素: `name` | ✅ 字符串 | ✅ 字符串 | ✅ |
| 每个元素: `available` | `"yes"`/`"no"` | `"yes"`/`"no"` | ✅ |
| 每个元素: `default` | `"enabled"`/`"disabled"` | `"enabled"`/`"disabled"` | ✅ |
| 每个元素: `effective` | `"enabled"`/`"disabled"` | `"enabled"`/`"disabled"` | ✅ |

> ⚠️ 每个 plugin 对象中字段排序：Python 按插入顺序 `name, available, default, effective`；Rust BTreeMap 按字母序 `available, default, effective, name`。JSON 对象键无序语义，不影响正确性。

### CLI 输出对比

| Python | Rust | 评估 |
|--------|------|------|
| Rich Table (Plugin, Available, Default, Effective 四列) | `✓/✗ name enabled/disabled` 纯文本 | ⚠️ 格式不同，但信息可读 |

---

## plugins enable / disable

### 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `name` (位置参数, 必填) | ✅ `str` | ✅ `String` | ✅ |
| `--json` | ✅ `bool = False` | ✅ `bool = False` | ✅ |

### JSON 输出对比（成功）

| 场景 | Python | Rust | 匹配? |
|------|--------|------|-------|
| enable | `{"ok":true,"plugin":"homebrew","action":"enabled"}` | `{"ok":true,"action":"enabled","plugin":"homebrew"}` | ✅ |
| disable | `{"ok":true,"plugin":"npm","action":"disabled"}` | `{"ok":true,"action":"disabled","plugin":"npm"}` | ✅ |

### JSON 输出对比（错误）

| 场景 | Python | Rust | 匹配? |
|------|--------|------|-------|
| unknown plugin | `{"ok":false,"error":"...","reason":"unknown_plugin","hint":"...","plugin_name":"nonexistent"}` | 完全一致 | ✅ (已修复) |
| exit code | 1 | 1 | ✅ |
| `plugin_name` 上下文 | ✅ | ✅ (已修复) | ✅ |

### CLI 输出对比

| Python | Rust | 评估 |
|--------|------|------|
| `Plugin [bold]{name}[/bold] {action} (persisted).` | `Plugin '{name}' {action}.` | ⚠️ 措辞微差 |

## 修复记录

| ID | 严重度 | 描述 | 修复 |
|----|--------|------|------|
| BUG-03 | BUG | enable/disable 错误 JSON 缺少 `plugin_name` 上下文字段 | 添加 `extra` BTreeMap 包含 `plugin_name` |
| BUG-04 | BUG | hint 文案 "Use `frais plugins list`" 应为 "Run `frais plugins list --json`" | 修正 hint 文案 |

## 结论

✅ **PASS** — 2 个 BUG 已修复。JSON 输出与 Python 完全一致。
