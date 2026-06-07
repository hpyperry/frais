# Code Review — 2025-06-07

**分支**: `rust-rewrite`
**范围**: 完整 Python → Rust 重写 (~7200 行新代码)
**方法**: 5 正确性角度 + 4 清理/架构角度 × 多子系统 → 验证 → 扫尾

---

## 高严重度（2 个）

### 1. `version_compare.rs:38` — is_newer 数字回退路径变量赋值颠倒

`src/plugins/applications/research/version_compare.rs`

**机制**：`digits_only()` 回退分支中，`Version::parse(&l2)` 结果赋给 `vc`，`Version::parse(&c2)` 赋给 `vl`，然后比较 `vl > vc`，实际等价于 `current > latest`——和函数语义相反。

```rust
// 行 26-27（正确）：
if let (Ok(vc), Ok(vl)) = (Version::parse(&cur), Version::parse(&lat)) {
    return vl > vc;  // vc=current, vl=latest, 正确
}

// 行 38-39（错误）：
let c2 = digits_only(&cur);
let l2 = digits_only(&lat);
if let (Ok(vc), Ok(vl)) = (Version::parse(&l2), Version::parse(&c2)) {
    return vl > vc;  // vc 实际是 latest 的解析结果, vl 实际是 current 的解析结果
                     // vl > vc 等价于 current_digits > latest_digits —— 颠倒！
}
```

**触发**：
```
is_newer(Some("1.0.0rc1"), Some("2.0.0rc2"))
→ digits_only("1.0.0rc1") = "1.0.01" (有效 semver)
→ digits_only("2.0.0rc2") = "2.0.02" (有效 semver)
→ vc = Version("2.0.2"), vl = Version("1.0.1")
→ vl > vc = 1.0.1 > 2.0.2 = false  ← 应为 true
```

**修复**：交换元组参数或比较方向，任选其一：
```rust
// 方案 A：交换元组，恢复变量名语义
if let (Ok(vc), Ok(vl)) = (Version::parse(&c2), Version::parse(&l2)) {

// 方案 B：保持元组，修正比较
return vc > vl;
```

该分支零测试覆盖。

---

### 2. `subprocess_json.rs:47` — 管道缓冲区死锁

`src/plugins/subprocess_json.rs`

**机制**：`run_json()` 以 `Stdio::piped()` 启动子进程后，在 `try_wait()` 自旋循环中从不读取 stdout/stderr。若子进程输出超过 OS 管道缓冲区（macOS 约 64KB），子进程写阻塞，永远无法退出，父进程永远收不到退出信号——死锁直到 60 秒超时。

```rust
// 行 46-67：等待循环——无任何 I/O
loop {
    match child.try_wait() {  // 只轮询退出状态
        Ok(Some(status)) => { success = status.success(); break; }
        Ok(None) => { /* 继续睡眠，不读管道 */ }
        Err(e) => return Err(...)
    }
    std::thread::sleep(Duration::from_millis(100));
}
// 行 69-86：此时才读取管道——已死锁，永远到不了这里
let stdout = child.stdout.take()...read_to_end()...
```

**影响范围**：所有使用 `run_json` 的调用——`brew outdated --json=v2`、`brew info --json=v2 --installed`、`npm outdated -g --json`、`npm ls -g --depth=0 --json`。Homebrew 大量安装时输出极易超过 64KB。

**修复**：在等待循环中启动线程并发读取管道，或使用异步方式。

---

## 中严重度（7 个）

### 3. `config_store.rs:137` — TOML 转义不完整

`src/store/config_store.rs`

```rust
fn toml_escape(value: &str) -> String {
    let escaped: String = value
        .replace('\\', "\\\\")
        .replace('"', "\\\"");
    format!("\"{}\"", escaped)
}
```

TOML 基本字符串要求所有控制字符（U+0000–U+001F，tab 除外）必须转义。该函数只处理 `\` 和 `"`。换行、回车等控制字符在任意配置值中出现即产生无效 TOML。

**触发**：API key 粘贴时带尾部换行 → `save_config` 写入无效 TOML → 下次 `load_config` 解析失败 → 配置静默丢失。

**修复**：用 `toml::to_string_pretty` + `#[derive(Serialize)]` 替代手写 TOML。

---

### 4. `plugin_store.rs:75` — 插件名作为裸 TOML 键写入

`src/store/plugin_store.rs`

```rust
plugins_section.push_str(&format!("{} = {}\n", name, enabled));
```

TOML 裸键仅允许 `[A-Za-z0-9_-]+`。名字含空格、点号或以数字开头的插件产生无效 TOML。

**触发**：插件名 `"My Plugin"` → 输出 `My Plugin = true` → 无效 TOML → `load_plugins_config` 静默返回空 map → 所有插件启用/禁用状态丢失。

**修复**：始终用双引号包裹并转义 `format!("\"{}\" = {}\n", toml_escape(name), enabled)`。

---

### 5. `web_tools.rs:294` — 互斥锁中毒导致数据全部丢失

`src/web_tools.rs`

```rust
urls.par_iter().for_each(|url| {
    let content = web_fetch(url);
    match results.lock() {
        Ok(mut map) => { map.insert(url.clone(), content); }
        Err(_) => {}   // ← 静默吞没所有存活线程的结果
    }
});
results.into_inner().unwrap_or_default()  // ← 丢弃被锁定的数据
```

任一 rayon 线程在持有锁时 panic → 互斥锁中毒 → 所有其他线程的 `lock()` 返回 `Err` → 数据全部丢弃。

**修复**：使用 `into_inner().unwrap_or_else(|e| e.into_inner())` 恢复中毒锁中的数据，并在 `lock()` 失败时记录日志。

---

### 6. `plugin.rs:142` — 顺序回退路径缺少 catch_unwind

`src/plugins/applications/plugin.rs`

并行路径（rayon）每步包裹 `catch_unwind`，但顺序回退路径（行 142-156）在 rayon `ThreadPoolBuilder::build()` 失败时直接调用 `research_application_update`，无 panic 保护。

**触发**：线程池构建失败 → 回退到 `for` 循环 → `research_application_update` panic → 无恢复 → 整个扫描崩溃。

**修复**：顺序路径也包裹 `catch_unwind`。

---

### 7. `plugin.rs:159` — Mutex::into_inner().unwrap_or_default() 丢弃中毒数据

`src/plugins/applications/plugin.rs`

```rust
let mut candidates = candidates.into_inner().unwrap_or_default();
```

若互斥锁中毒，`into_inner()` 返回 `Err(PoisonError)`，`unwrap_or_default()` 返回空 `Vec`。panic 前已收集的所有研究结果静默丢弃，无日志。

**修复**：`into_inner().unwrap_or_else(|e| e.into_inner())`。

---

### 8. `web_tools.rs:34` — OnceLock 中 .expect() 延迟崩溃

`src/web_tools.rs`

```rust
static CLIENT: OnceLock<reqwest::blocking::Client> = OnceLock::new();
CLIENT.get_or_init(|| {
    reqwest::blocking::Client::builder()
        .build()
        .expect("Failed to build DDGS HTTP client")  // 首次调用时 panic
})
```

`get_fetch_client()`（行 49）同样模式。TLS 后端配置错误或系统代理异常时，首次调用 `web_search()`/`web_fetch()` 直接崩溃——尽管调用方已能处理空结果。

---

### 9. `deepseek.rs:229` — web_search 未检查 HTTP 响应状态码

`src/llm/deepseek.rs`

`DeepSeekAnthropicClient::web_search` 不检查响应状态码——4xx/5xx 错误被静默吞没，返回空结果，无日志。与同文件的 `chat()` 方法和 `openai_compat.rs` 的 `create()` 不一致。

---

## 低-中严重度（6 个）

### 10. `advise.rs:56` — SIGINT 处理器永不恢复

`src/cli/advise.rs`

```rust
let _orig_handler = super::signal::install_interrupt_handler();
```

`_orig_handler`（恢复原始 SIGINT 处理器的闭包）以 `_` 前缀存储，在 `run()` 返回时被静默丢弃，从未执行。自定义处理器（调用 `libc::_exit(130)`）在 `advise` 返回后仍然常驻。当前无实际影响（进程立即退出），但违反 RAII 契约。

---

### 11. `update.rs:159` — 缺失 plugin_map 条目静默跳过更新

`src/cli/update.rs`

```rust
let plugin_name = plugin_map.get(&candidate.item.id);
let plugin = plugin_name.and_then(|n| plugins.get(n));
if let Some(plugin) = plugin {
    // 执行更新...
}
// 如果 plugin_map 无此条目，静默跳过，无错误/警告
```

缓存损坏或格式不匹配时，用户输入 "y" 后无任何反馈。

---

### 12. `summarize.rs:147` — save_scan_cache 错误被丢弃

`src/cli/summarize.rs`

```rust
let _ = crate::store::scan_cache::save_scan_cache(...);
```

LLM 总结生成成功后，缓存写入失败被静默吞没。用户看到成功输出，但下次 `frais advise` 重新生成。与 `advise.rs:300-306` 不一致（那边有 `log::warn!`）。

---

### 13. `openai_compat.rs:89` — URL 路径重复拼接

`src/llm/openai_compat.rs`

```rust
let endpoint = format!("{}/v1/chat/completions", self.config.url.trim_end_matches('/'));
```

用户配置 `url = "http://localhost:8000/v1"`（vLLM/llama.cpp 常见模式）→ 结果 `http://localhost:8000/v1/v1/chat/completions` → 404。

**修复**：检查 URL 是否已以 `/v1` 结尾。

---

### 14. `models.rs:21` — SourceKind 缺少 #[serde(other)]

`src/models.rs`

`SourceKind` 枚举无 `#[serde(other)]` 兜底变体。新版 frais 新增变体后，旧版反序列化缓存文件时直接失败 → `cache_read_error` → 整个扫描结果不可读。破坏前向兼容。

---

### 15. `scan_progress.rs:88` — 中毒互斥锁导致级联 panic

`src/cli/scan_progress.rs`

四处 `self.last_step.lock().unwrap()` / `self.scan_elapsed.lock().unwrap()`。任一线程在持有锁时 panic → 互斥锁中毒 → 下次 `.unwrap()` 触发双重 panic → 进程 abort → 用户看到崩溃而非部分结果。

---

## 低严重度 / 清理（7 个）

### 16. `web_tools.rs:364` — 每次调用重新编译 Regex

`extract_text()` 每次调用创建 4 个 `Regex`。`web_fetch_batch` 批量抓取 N 个 URL 时编译 4N 次。应改为 `once_cell::sync::Lazy<Regex>` 静态变量（`GITHUB_REPO_RE` 已有此模式）。

---

### 17. `openai_compat.rs:20` — _base_url 计算后未使用

`new()` 中计算 `_base_url` 但从不读取，相同逻辑在 `create()` 中重复执行。死代码 + 维护陷阱。

---

### 18. `providers.rs:104` — get_provider() 每次调用重新分配

`builtin_providers()` 每次调用构造新 `Vec<Provider>`。`load_config` 热路径上重复分配。

---

### 19. `config_store.rs:29` — 纯空白 API key 通过 is_ready()

```rust
pub fn is_ready(&self) -> bool {
    !self.api_key.is_empty() && !self.model.is_empty()
}
```

`"  "` 通过 `!is_empty()` → 下游 API 返回 401，错误信息模糊。

---

### 20. `subprocess_json.rs:72` — stdout 读取错误被吞没

`read_to_end` 失败时 `unwrap_or(0)` 返回空 buffer → 调用者收到空 JSON 对象，无错误指示。

---

### 21. `cli/config.rs:598` — save_config 失败映射为 "cancelled"

`map_err(|_| ConfigCancelled)` → 磁盘满时用户被告知 "Configuration cancelled" 而非真实的保存失败原因。

---

### 22. `json_parser.rs:42` — extract_balanced 不感知 JSON 字符串

字符串字面量内的 `{` `}` 被误计为结构分隔符 → 包含花括号的字符串值导致提取失败。

---

## 测试相关

### 23. `tests/cli_integration_test.rs:178` — 硬编码插件数量

```rust
assert_eq!(plugins.len(), 3);
```

新增插件必然破坏此测试。

### 24. `tests/cli_integration_test.rs:159` — 硬编码插件名称

`str::contains("applications")` / `"homebrew"` / `"npm"` —— 改名或移除插件破坏测试。

### 25. `.github/workflows/ci.yml` — 无依赖缓存

所有 job 每次重新编译依赖，增加 2-5 分钟 CI 时间。应加 `Swatinem/rust-cache@v2`。

### 26. `.github/workflows/ci.yml` — release job 无测试依赖

Release job 不 `needs: [test, clippy, fmt]`——可对未通过测试的提交打 tag 并发布。

---

## 修复优先级

| 优先级 | # | 文件 | 修复难度 |
|--------|---|------|----------|
| P0 | 1 | `version_compare.rs:38` | 一行修复 + 测试 |
| P0 | 2 | `subprocess_json.rs:47` | 架构调整（线程读取管道） |
| P1 | 3,4 | `config_store.rs` + `plugin_store.rs` | 中等（切换为序列化器） |
| P1 | 5,7 | `web_tools.rs` + `plugin.rs` | 一行修复（恢复中毒数据） |
| P1 | 6 | `plugin.rs:142` | 一行修复（加 catch_unwind） |
| P2 | 8-15 | 各处 | 小改动 |
| P3 | 16-26 | 清理/测试/CI | 按需 |
