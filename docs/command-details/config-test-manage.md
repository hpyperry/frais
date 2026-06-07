# config test + config manage 验证详情

**日期**: 2026-06-07
**状态**: ✅ pass（3 个 BUG 已修复）

---

## config test

### 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `--json` | ✅ `bool = False` | ✅ `bool = False` | ✅ |

### JSON 输出对比（成功）

| 字段 | Python | Rust (修复后) | 匹配? |
|------|--------|-------------|-------|
| `ok` | `true` | `true` | ✅ |
| `provider` | `"DeepSeek"` (显示名称) | `"DeepSeek"` (显示名称) | ✅ (已修复) |
| `model` | 配置的 model id | 一致 | ✅ |
| `url` | 配置的 endpoint url | 一致 | ✅ |
| `response` | LLM 响应文本 `.strip()` | 一致 | ✅ |

### JSON 输出对比（错误）

| 错误场景 | Python exit / reason | Rust exit / reason | 匹配? |
|---------|---------------------|-------------------|-------|
| config_missing | exit 2, reason=config_missing | exit 2, reason=config_missing | ✅ |
| connection_error | exit 2, reason=connection_error | exit 2, reason=connection_error | ✅ (已修复) |

### CLI 输出对比

| Python | Rust (修复后) | 匹配? |
|--------|-------------|-------|
| Provider: DeepSeek | Provider: DeepSeek | ✅ |
| Model: deepseek-v4-flash | Model: deepseek-v4-flash | ✅ |
| URL: ... | URL: ... | ✅ |
| LLM test response: ok | LLM test response: ok | ✅ |

---

## config manage

交互式命令，无 `--json`。Rust 使用 `dialoguer` (Select + Input + Confirm + rpassword)，Python 使用 `rich.prompt` + `typer.prompt` + `getpass`。

### 流程对比

| 步骤 | Python | Rust | 匹配? |
|------|--------|------|-------|
| 已配置 → 显示当前配置 | Rich + 颜色 | console::style + 颜色 | ✅ |
| 已配置 → 选择修改内容 | 4 选项 (Provider, Key, Everything, Cancel) | 4 选项 (dialoguer Select) | ✅ |
| Provider 选择 | 编号列表 | dialoguer Select | ✅ |
| Model 选择 | 编号列表 | dialoguer Select | ✅ |
| Protocol 选择 | 编号列表 (单协议自动选择) | dialoguer Select (单协议自动选择) | ✅ |
| URL 输入 | typer.prompt (default, "-"=reset, "back") | dialoguer Input (同逻辑) | ✅ |
| API Key 输入 | getpass (隐藏输入) | rpassword (隐藏输入) | ✅ |
| 连接测试 | 创建 client, test_connection() | 同逻辑 | ✅ |
| 测试失败 → 确认保存？ | typer.confirm (default=False) | dialoguer Confirm (default=false) | ✅ |
| 原子保存 | .tmp → .replace() | .tmp → rename() | ✅ |
| Ctrl+C 取消 | 显示 "Configuration cancelled" | 显示 "Configuration cancelled" | ✅ |

## 修复记录

| ID | 严重度 | 描述 | 修复 |
|----|--------|------|------|
| BUG-05 | BUG | config test JSON `provider` 返回 `"deepseek"` (ID) 而非 `"DeepSeek"` (显示名称) | 通过 `get_provider()` 查找显示名称 |
| BUG-06 | BUG | config test connection_error exit code 为 1，Python 为 2 | 改为 exit_code=2 |
| BUG-07 | BUG | config test connection_error hint 文案缺少 "then try again." | 修正 hint 文案 |
| COS-05 | COSMETIC | config test CLI 输出缺少 Provider/Model/URL 分行 | 改为分行显示 |

## 结论

✅ **PASS** — 3 个 BUG + 1 个 COSMETIC 已修复。JSON/CLI 输出与 Python 完全一致。config manage 交互流程与 Python 等价。
