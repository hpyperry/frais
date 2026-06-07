# --version / -v 验证详情

**日期**: 2026-06-07
**状态**: ✅ pass

---

## 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `--version` | ✅ 支持 | ✅ 支持 | ✅ |
| `-v` | ✅ 支持 | ✅ 支持 | ✅ |
| `--json` (与 version 组合) | ✅ 支持 | ✅ 支持 | ✅ |

## 逻辑流程对比

| 步骤 | Python (`cli.py:257-262`) | Rust (`main.rs:17-29`) | 匹配? |
|------|--------------------------|------------------------|-------|
| 1. 检测 `--version`/`-v` | `sys.argv` 扫描 | `std::env::args()` 扫描 | ✅ |
| 2. 检测 `--json` | `"--json" in args` | `args.iter().any(\|a\| a == "--json")` | ✅ |
| 3. JSON 输出 | `print_json_success(version=...)` → `{"ok":true,"version":"0.1.0"}` | `format!(r#"{{"ok":true,"version":"{}"}}"#, version)` | ✅ |
| 4. 纯文本输出 | `console.print(f"frais {version}")` | `println!("frais {}", version)` | ✅ |
| 5. 退出码 | `sys.exit(0)` | `process::exit(0)` | ✅ |

## 实际运行结果

### --version (纯文本)
```
Python: frais 0.1.0
Rust:   frais 0.1.0
→ 完全一致
```

### -v (短参数)
```
Python: frais 0.1.0
Rust:   frais 0.1.0
→ 完全一致
```

### --version --json
```
Python: {"ok":true,"version":"0.1.0"}  (Rich pretty-print, indent=2)
Rust:   {"ok":true,"version":"0.1.0"}  (compact single line)
→ 内容完全一致；JSON 都是合法 JSON，紧凑 vs 美化格式属于可接受差异
```

### 参数顺序变化 (-v --json, --json --version)
```
Python 和 Rust 均正确处理，输出一致
```

## 边界情况

| 边界情况 | Python | Rust | 匹配? |
|----------|--------|------|-------|
| 参数顺序无关 | ✅ | ✅ | ✅ |
| exit code 始终 0 | ✅ | ✅ | ✅ |
| version 值来自 `__version__` | "0.1.0" | env!("CARGO_PKG_VERSION") = "0.1.0" | ✅ |

## 发现的差异

**无。** JSON pretty-print vs compact 是可接受的格式差异，内容完全一致。

## 结论

✅ **PASS** — `--version` / `-v` 标志行为与 Python 实现完全一致。
