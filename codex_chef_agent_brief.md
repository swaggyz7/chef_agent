# AI 私厨 Agent 实现摘要

本文件用于记录当前项目与《第2节. Agent入门实战（AI私厨）》指导方案的一致实现。

## 目标能力

- 图片识别：用户上传冰箱或厨房照片，多模态模型识别可见食材。
- 智能搜索：优先调用 `web_search`，根据食材搜索可行菜谱。
- 智能排序：按营养价值和制作难度进行量化评分。
- 创意建议：搜索结果不足时，由模型给出合理搭配。
- 多轮对话：使用 SQLite Checkpointer 按 `thread_id` 保存会话。
- Web 界面：FastAPI 托管静态聊天页，支持图片上传和文本对话。

## 核心技术选型

- Agent：LangChain 1.0 `create_agent`
- 模型：`qwen3.5-plus`
- 模型接入：OpenAI 兼容协议，阿里百炼 DashScope Base URL
- 搜索：Tavily `TavilySearch`
- 记忆：`langgraph.checkpoint.sqlite.SqliteSaver`
- 服务端：FastAPI + Uvicorn
- 图片存储：阿里云 OSS 预签名 URL，浏览器直传
- 开发降级：OSS 未配置时保存到 `app/static/uploads/`

## 关键接口

- `POST /api/v1/chat/stream`：流式对话
- `GET /api/v1/chat/messages`：查询历史
- `DELETE /api/v1/chat/messages`：清空历史
- `POST /api/v1/oss/presign`：创建 OSS 上传签名
- `POST /api/v1/oss/local-upload`：本地开发图片上传
- `GET /api/v1/status`：查看模型、Tavily 和 OSS 配置状态

## 配置原则

- API Key 只放在 `.env`，仓库只提交 `.env.example`。
- `DASHSCOPE_API_KEY`、`TAVILY_API_KEY` 和 OSS 密钥均允许为空。
- 空 Key 不应导致 FastAPI 启动失败；对话时应返回清晰的配置提示。
- OSS Bucket 仅用于课程测试时可临时公共读，正式项目必须使用私有权限和 CDN。