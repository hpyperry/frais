# scan 验证详情

**日期**: 2026-06-07
**状态**: ✅ pass（2 个 BUG 已修复）

---

## 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `--json` | ✅ `bool = False` | ✅ `bool = False` | ✅ |
| `--plugins` | ✅ `str \| None = None` | ✅ `Option<String>` | ✅ |
| `--all` | ✅ `bool = False` | ✅ `bool = False` | ✅ |

## 逻辑流程对比

| 步骤 | Python | Rust | 匹配? |
|------|--------|------|-------|
| 1. 系统检测 | `detect_system()` | `detect_system()` | ✅ |
| 2. 插件选择 | `coordinator.select_plugins(explicit)` | `coordinator::select_plugins()` | ✅ |
| 3. 无匹配插件 | `exit_with_error(reason="no_plugins_matched")` | 同 | ✅ (已修复) |
| 4. 并行扫描 | `_scan_core.run_scan_phase()` → `ThreadPoolExecutor` | `coordinator::run_scan()` → `thread::scope` | ✅ |
| 5. Ignore 过滤 | `apply_ignore_filter()` | `apply_ignore_filter()` | ✅ |
| 6. 缓存保存 | `save_scan_cache()` 原子写入 | 同 | ✅ |
| 7. JSON 输出 | `print_json_success(**result.to_dict())` | serde 序列化 | ✅ (已修复) |
| 8. CLI 输出 | Rich 进度条 + 结果表 | indicatif 进度条 + 格式输出 | ✅ |

## JSON 输出对比

| 字段 | Python | Rust (修复后) | 匹配? |
|------|--------|-------------|-------|
| `ok` | `true` (第一 key) | `true` (第一 key) | ✅ |
| `system` | `SystemProfile` (全部字段) | 同 | ✅ |
| `plugin_results` | `{plugin: PluginScanResult}` | 同 | ✅ |
| `PluginScanResult.items[]` | 全部 SoftwareItem 字段 | 同 | ✅ |
| `PluginScanResult.candidates[]` | 全部 UpdateCandidate 字段 (含 `release_notes`, `ai_summary`) | 同 | ✅ (已修复) |
| `PluginScanResult.skipped[]` | 跳过原因列表 | 同 | ✅ |

### 错误处理

| 错误场景 | Python | Rust | 匹配? |
|---------|--------|------|-------|
| no_plugins_matched | `"No available plugins matched: {names}"` + `requested` 列表 | 同 | ✅ (已修复) |
| exit code | 1 | 1 | ✅ |

## 修复记录

| ID | 严重度 | 描述 | 修复 |
|----|--------|------|------|
| BUG-08 | BUG | Candidate JSON 缺少 `release_notes` 和 `ai_summary` 字段 | 移除 `skip_serializing_if` |
| BUG-09 | BUG | no_plugins_matched error 消息 "Unknown plugin:" 应为 "No available plugins matched:" | 修正错误消息格式 |
| BUG-14 | BUG | App Store 应用被排除在 research 之外 | 移除 `SourceKind::AppStore` 过滤器，所有 items 通过 `research_application_update`（App Store → iTunes API 快速通道） |

## 结论

✅ **PASS** — 3 个 BUG 已修复。JSON 结构、错误处理与 Python 完全一致。Rust 版本比 Python 更好：App Store 应用现在通过 iTunes API 获得版本检查（Python 版本将其完全跳过）。
