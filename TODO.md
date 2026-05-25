# 优先级
1. LLM支持
2. 功能

# LLM 支持
## provider支持
- deepseek:
  - openai: 已支持
  - anthropic: 已支持
- 小米Mimo：
  -  openai: 已支持
   - anthropic: 暂不接入
## provider对应websearch server-side 支持
- deepseek
    - openai: 不支持
    - anthropic: /Users/hpy/Workspace/claude-code-fork-main/web_search_tool
- 小米Mimo: https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/tool-calling/web-search
    - openai:
```python

import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("MIMO_API_KEY"),
    base_url="https://api.xiaomimimo.com/v1"
)

completion = client.chat.completions.create(
    model="mimo-v2.5-pro",
    messages=[
        {
            "role": "system",
            "content": "You are MiMo, an AI assistant developed by Xiaomi. Today is date: Tuesday, December 16, 2025. Your knowledge cutoff date is December 2024."
        },
        {
            "role": "user",
            "content": "please introduce Jun Lei"
        }
    ],
    max_completion_tokens=1024,
    temperature=1.0,
    top_p=0.95,
    stream=False,
    stop=None,
    frequency_penalty=0,
    presence_penalty=0,
    extra_body={
        "thinking": {"type": "disabled"}
    },
    tools=[
        {
            "type": "web_search",
            "max_keyword": 3,
            "force_search": True,
            "limit": 1,
            "user_location": {
                "type": "approximate",
                "country": "China",
                "region": "Hubei",
                "city": "Wuhan"
            }
        }
    ],
    tool_choice="auto"
)

print(completion.model_dump_json())
```
   - anthropic: 不支持
# 遗留问题

## bug
 - LLM的baseurl
  1. 需要确认默认值是否区分了协议
  2. manage显示的当前base url并没有区分模型，导致用户查看时已经切换了供应商但是url还是之前供应商的
## 优化
- cli输出/json输出，需要根据plugin分组
- applications插件的research流程，耗时问题
  - 优先：Provider的webSearch
  - fallback: DDGS

## 功能
- scan / advise / summarize: 需要支持模糊搜索, --fuzy vscode。对app name/ id搜索


