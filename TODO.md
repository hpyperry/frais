# 优先级
1. LLM支持
2. 功能

# LLM 支持
## provider支持
- deepseek:
  - openai: 已支持
  - anthropic: 已支持（含 web_search）
- 小米Mimo：
  - openai: 已支持
  - anthropic: 暂不接入

## provider对应websearch server-side 支持
- deepseek
  - openai: 不支持
  - anthropic: 已支持 ✅
- 小米Mimo
  - openai: 待接入（有 API 示例）
  - anthropic: 不支持

# 遗留问题

## bug
（无）

## 优化
- cli输出/json输出，需要根据plugin分组 ✅
- applications插件的research流程，耗时问题
  - 优先：Provider的webSearch（DeepSeek Anthropic ✅，MiMo 待接入）
  - fallback: DDGS

## 功能
- scan / advise / summarize: 需要支持模糊搜索, --fuzzy vscode。对app name/ id搜索
