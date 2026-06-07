# ignore 验证详情

**日期**: 2026-06-07
**状态**: ✅ pass（3 个 COSMETIC 文案差异已修复）

---

## ignore list

### 参数对比

| 参数 | Python | Rust | 匹配? |
|------|--------|------|-------|
| `--json` | ✅ `bool = False` | ✅ `bool = False` | ✅ |

### JSON 输出对比

| 场景 | Python | Rust | 匹配? |
|------|--------|------|-------|
| 空列表 | `{"ok":true,"ignored":[],"count":0}` | `{"ok":true,"count":0,"ignored":[]}` | ✅ |
| 有内容 | `{"ok":true,"ignored":["sorted"],"count":N}` | 同结构 | ✅ |
| `ignored` 排序 | `sorted(ids)` | BTreeSet 自动排序 | ✅ |

### CLI 输出对比

| 场景 | Python | Rust (修复后) | 匹配? |
|------|--------|-------------|-------|
| 空 | `No ignored apps.` | `No ignored apps.` | ✅ |
| 有内容 | `Ignored apps (N):` + ID 列表 | 同格式 | ✅ |

---

## ignore add

### JSON 输出对比

| 场景 | Python | Rust | 匹配? |
|------|--------|------|-------|
| 新增 | `{"ok":true,"app_id":"com.x","action":"added"}` | 同字段 | ✅ |
| 重复 | `{"ok":true,"app_id":"com.x","action":"already_ignored"}` | 同字段 | ✅ |

### CLI 输出对比

| 场景 | Python | Rust (修复后) | 匹配? |
|------|--------|-------------|-------|
| 新增 | `Added: com.x` | `Added: com.x` | ✅ |
| 重复 | `Already ignored: com.x` | `Already ignored: com.x` | ✅ |

---

## ignore remove

### JSON 输出对比

| 场景 | Python | Rust | 匹配? |
|------|--------|------|-------|
| 移除 | `{"ok":true,"app_id":"com.x","action":"removed"}` | 同字段 | ✅ |
| 不存在 | `{"ok":true,"app_id":"com.x","action":"not_in_list"}` | 同字段 | ✅ |

### CLI 输出对比

| 场景 | Python | Rust (修复后) | 匹配? |
|------|--------|-------------|-------|
| 移除 | `Removed: com.x` | `Removed: com.x` | ✅ |
| 不存在 | `Not in ignore list: com.x` | `Not in ignore list: com.x` | ✅ |

---

## 修复记录

| ID | 严重度 | 描述 | 修复 |
|----|--------|------|------|
| COS-02 | COSMETIC | ignore list 空："No ignored applications." → "No ignored apps." | 修正文案 |
| COS-03 | COSMETIC | ignore list 非空："Ignored applications:" + "Total: N" → "Ignored apps (N):" | 修正格式 |
| COS-04 | COSMETIC | add/remove 文案格式："Added '{}' to ignore list." → "Added: {}" | 修正文案 |

## 结论

✅ **PASS** — 3 个 COSMETIC 文案差异已修复。JSON/CLI 输出与 Python 完全一致。
