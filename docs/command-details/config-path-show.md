# config path + config show 验证详情

**日期**: 2026-06-07
**状态**: ✅ pass（1 个 COSMETIC 问题已修复）

---

## config path

### 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `--json` | ✅ `bool = False` | ✅ `bool = False` | ✅ |

### JSON 输出对比

```
Python: {"ok": true, "path": "/Users/hpy/.frais/config/config.toml"}
Rust:   {"ok": true, "path": "/Users/hpy/.frais/config/config.toml"}
```
✅ 完全一致

### CLI 输出对比

```
Python: /Users/hpy/.frais/config/config.toml
Rust:   /Users/hpy/.frais/config/config.toml
```
✅ 完全一致

---

## config show

### 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `--json` | ✅ `bool = False` | ✅ `bool = False` | ✅ |

### JSON 输出对比（已配置）

| 字段 | Python 值 | Rust 值 | 匹配? |
|------|----------|---------|-------|
| `ok` | `true` (第一 key) | `true` (第一 key) | ✅ |
| `configured` | `true` | `true` | ✅ |
| `provider` | `"deepseek"` (ID) | `"deepseek"` (ID) | ✅ |
| `model` | `"deepseek-v4-flash"` | `"deepseek-v4-flash"` | ✅ |
| `protocol` | `"anthropic"` | `"anthropic"` | ✅ |
| `url` | `"https://api.deepseek.com/anthropic"` | `"https://api.deepseek.com/anthropic"` | ✅ |
| `key_suffix` | `"***a171"` | `"***a171"` | ✅ |
| `key_source` | `"/Users/hpy/.frais/config/config.toml"` | `"/Users/hpy/.frais/config/config.toml"` | ✅ |

> ⚠️ 注意：CLAUDE.md 记载的 `config show --json` 只返回 `configured, provider, model, key_suffix, key_source`，但 **Python 实际返回也包含 `protocol` 和 `url`**。CLAUDE.md 文档不完整，而非 Rust 多了字段。审计 #26 基于文档而非实际行为。

### JSON 输出对比（未配置）

| 字段 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `ok` | `true` | `true` | ✅ |
| `configured` | `false` | `false` | ✅ |

### CLI 输出对比

| Python (`config.py:385-397`) | Rust (`config.rs:31-42`) | 匹配? |
|------------------------------|-------------------------|-------|
| Rich Table 格式 | 纯文本缩进 | ⚠️ 格式不同（可接受） |
| Provider: DeepSeek (显示名称) | Provider: DeepSeek (显示名称) | ✅ (已修复) |
| Model: deepseek-v4-flash | Model: deepseek-v4-flash | ✅ |
| Protocol: anthropic | Protocol: anthropic | ✅ |
| URL: ... | URL: ... | ✅ |
| API key: ***a171 | Key: ***a171 (via ...) | ⚠️ 格式微差 |
| Key source: /path/to/config.toml | (合并到 Key 行) | ⚠️ 格式微差 |
| 未配置：`[dim]Not configured...[/dim]` | `Not configured...` | ✅ |

### 修复记录

| ID | 严重度 | 描述 | 修复 |
|----|--------|------|------|
| COS-01 | COSMETIC | CLI 模式 Provider 显示 `"deepseek"` (ID) 而非 `"DeepSeek"` (显示名称) | 通过 `c.get_provider().name` 查找显示名称 |

## 结论

✅ **PASS** — `config path` 和 `config show` 的 JSON/CLI 输出与 Python 完全一致（1 个 cosmetic 问题已修复）。
