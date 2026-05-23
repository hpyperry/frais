# Python 工程开发规范（严格版）

> 版本：v1.0  
> 适用于：
>
> - 中大型 Python 项目
> - Agent / CLI / Backend / SDK
> - 多人协作
> - 长期维护
> - 高可靠性系统

---

# 1. 核心原则

## 1.1 可读性优先

代码首先是给人看的，其次才是机器执行。

### 禁止

```python
result = [x.id for x in users if x and x.active and x.role == "admin"]
```

### 允许

```python
admin_ids: list[int] = []

for user in users:
    if user is None:
        continue

    if not user.active:
        continue

    if user.role != "admin":
        continue

    admin_ids.append(user.id)
```

---

## 1.2 显式优于隐式

### 禁止

```python
x = data and data[0] or {}
```

### 允许

```python
if data:
    first_item = data[0]
else:
    first_item = {}
```

---

## 1.3 单一职责原则

一个模块、类、函数只能负责一件事。

### 禁止

```python
def process_user():
    validate_user()
    query_database()
    send_email()
    upload_s3()
```

### 允许

```python
def process_user(user_id: int) -> None:
    user = load_user(user_id)

    validate_user(user)

    notify_user(user)
```

---

## 1.4 禁止魔法行为

禁止：

- monkey patch
- 动态修改 class
- import side effect
- runtime 注入
- 隐式全局状态

---

# 2. 工程结构规范

## 2.1 标准目录结构

```text
project/
├── pyproject.toml
├── README.md
├── Makefile
├── .gitignore
├── .env.example
├── src/
│   └── app/
│       ├── __init__.py
│       ├── main.py
│       ├── config/
│       ├── core/
│       ├── services/
│       ├── repositories/
│       ├── models/
│       ├── schemas/
│       ├── clients/
│       ├── utils/
│       ├── exceptions/
│       └── constants/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── scripts/
├── docs/
└── logs/
```

---

## 2.2 模块命名规范

### 允许

```text
token_validator.py
openai_client.py
json_parser.py
```

### 禁止

```text
utils.py
helpers.py
common.py
misc.py
temp.py
```

---

# 3. 类型系统规范

## 3.1 强制类型标注

所有参数、返回值、成员变量必须标注类型。

### 禁止

```python
def get_user(id):
```

### 允许

```python
def get_user(user_id: int) -> User:
```

---

## 3.2 禁止 Any 泛滥

### 禁止

```python
data: Any
```

### 允许

```python
data: dict[str, str]
```

---

## 3.3 强制 mypy strict

```toml
[tool.mypy]
strict = true
```

---

# 4. 函数规范

## 4.1 函数长度限制

硬性要求：

- 普通函数 ≤ 50 行
- 核心逻辑 ≤ 30 行

---

## 4.2 参数数量限制

超过 4 个参数必须封装对象。

### 禁止

```python
def create_user(
    name,
    age,
    email,
    phone,
    address,
):
```

### 允许

```python
@dataclass
class CreateUserRequest:
    name: str
    age: int
    email: str
```

---

## 4.3 禁止布尔参数地狱

### 禁止

```python
save(data, True, False, True)
```

### 允许

```python
save(
    data=data,
    overwrite=True,
    validate=False,
    backup=True,
)
```

---

# 5. 类设计规范

## 5.1 类命名必须表达职责

### 禁止

```python
class Manager:
class Handler:
class Processor:
```

### 允许

```python
class UserRepository:
class OpenAIClient:
class TokenValidator:
```

---

## 5.2 类长度限制

建议：

- ≤ 300 行

---

## 5.3 优先组合而非继承

禁止深层继承：

```text
A -> B -> C -> D
```

---

# 6. 异常规范

## 6.1 禁止裸 except

### 禁止

```python
try:
    ...
except:
    pass
```

### 允许

```python
try:
    ...
except ValueError as exc:
    logger.exception("parse failed")
    raise
```

---

## 6.2 禁止吞异常

### 禁止

```python
except Exception:
    return None
```

---

# 7. 日志规范

## 7.1 禁止 print

### 禁止

```python
print("error")
```

### 允许

```python
logger.error("user login failed")
```

---

## 7.2 日志必须结构化

```python
logger.info(
    "user created",
    extra={
        "user_id": user.id,
        "role": user.role,
    },
)
```

---

# 8. 配置规范

## 8.1 禁止硬编码

### 禁止

```python
API_KEY = "xxx"
```

---

## 8.2 配置统一管理

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openai_api_key: str
```

---

# 9. 并发规范

## 9.1 IO 使用 async

适用于：

- HTTP
- DB
- 文件
- Agent 调度

---

## 9.2 禁止阻塞 async

### 禁止

```python
async def run():
    time.sleep(1)
```

### 允许

```python
async def run():
    await asyncio.sleep(1)
```

---

# 10. 测试规范

## 10.1 测试分类

```text
unit/
integration/
e2e/
```

---

## 10.2 核心逻辑覆盖率要求

最低：

```text
80%
```

核心模块：

```text
90%+
```

---

# 11. CLI 工程规范

## 11.1 CLI 使用 Typer

```python
import typer

app = typer.Typer()
```

---

## 11.2 错误码规范

| code | 含义 |
|---|---|
| 0 | success |
| 1 | unknown error |
| 2 | invalid argument |
| 3 | network error |

---

# 12. Agent 工程规范

## 12.1 Tool 必须纯职责

禁止：

- 一个 tool 做多个领域动作
- 一个 tool 内部同时读写多个系统

---

## 12.2 LLM 输出必须校验

### 禁止

```python
json.loads(response)
```

### 允许

```python
class Output(BaseModel):
    answer: str
```

---

## 12.3 Prompt 必须版本化

```text
prompts/
├── v1/
├── v2/
```

---

# 13. 安全规范

## 13.1 禁止 eval

### 禁止

```python
eval(user_input)
```

---

## 13.2 禁止 pickle 反序列化不可信数据

---

# 14. Git 规范

## 14.1 Commit 规范

格式：

```text
type(scope): message
```

### 示例

```text
feat(auth): add token refresh
fix(cli): handle empty input
refactor(agent): split planner
```

---

## 14.2 禁止直接提交 main

必须：

- PR
- Review
- CI

---

# 15. CI/CD 规范

## 15.1 CI 必须包含

```text
lint
mypy
test
security
```

---

## 15.2 强制格式化

推荐：

- ruff
- black

---

# 16. 性能规范

## 16.1 禁止重复 IO

### 禁止

```python
for user_id in ids:
    db.query(...)
```

---

## 16.2 缓存必须可控

必须：

- TTL
- 最大容量
- 失效机制

---

# 17. 依赖管理规范

## 17.1 使用 pyproject.toml

禁止：

```text
requirements.txt 地狱
```

---

## 17.2 锁定版本

### 禁止

```text
httpx>=0.20
```

### 允许

```text
httpx==0.27.0
```

---

# 18. 文档规范

## 18.1 README 必须包含

- 项目介绍
- 安装方式
- 启动方式
- 配置说明
- 示例

---

## 18.2 公共函数必须有 docstring

```python
def create_user(name: str) -> User:
    '''
    Create a new user.
    '''
```

---

# 19. 最终红线（强制）

禁止：

- 超长函数
- 超长类
- 全局状态污染
- copy-paste 编程
- 无测试提交
- 无类型代码
- 无日志错误
- 裸 except
- print 调试
- import *
- 隐式副作用
- 魔法代码
- 动态猴子补丁

---

# 推荐工具链

| 类型 | 推荐 |
|---|---|
| 包管理 | uv / poetry |
| Lint | ruff |
| 格式化 | black |
| 类型检查 | mypy |
| 测试 | pytest |
| async 测试 | pytest-asyncio |
| 覆盖率 | coverage |
| pre-commit | pre-commit |
| CLI | typer |
| 配置 | pydantic-settings |
| ORM | SQLAlchemy |
| HTTP | httpx |
| 日志 | structlog |

---

# 推荐 Makefile

```makefile
lint:
	ruff check .

format:
	black src tests

typecheck:
	mypy src

test:
	pytest

check: lint typecheck test
```

---

# 推荐 pyproject.toml

```toml
[tool.black]
line-length = 88

[tool.ruff]
line-length = 88

[tool.mypy]
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
```
