# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NL2SQL 智能问数系统 — 基于自然语言的数据查询工具。用户用中文提问，AI 自动生成 SQL 查询 MySQL 数据库并返回结果和分析总结。

## Tech Stack

- **后端**: Python 3.12 + FastAPI
- **数据库**: MySQL
- **LLM**: 支持 Claude / 通义千问 / DeepSeek 切换
- **前端**: 单页 HTML + Tailwind CSS

## Commands

```bash
# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

# 测试 API
curl -X POST http://127.0.0.1:8000/api/ask -H "Content-Type: application/json" -d '{"question":"上个月回款多少"}'
```

## Architecture

```
main.py              → FastAPI 入口, /api/ask, /api/ask/stream, /api/schema, /api/reports
engine/
  schema_loader.py   → 读取 INFORMATION_SCHEMA, list_tables_text() 输出表名+注释
  llm_client.py      → LLM 抽象层 (Claude/Qwen/DeepSeek)
  sql_executor.py    → 安全 SQL 执行 (仅 SELECT, 限 100 行)
  nl2sql.py          → 两步流程: ①选表 ②生成SQL+执行+总结
config.py            → 从 .env 读取配置
frontend/index.html  → 前端页面
```

## NL2SQL 两步流程

1. **选表**: 把表名+注释+业务词典发给 LLM，让它根据问题选出相关表
2. **生成 SQL**: 只加载选中表的完整 schema + few-shot 示例，生成 SQL

## API

- `POST /api/ask` — 一次性返回结果
- `POST /api/ask/stream` — SSE 流式返回，逐步推送思考过程
- `GET /api/schema` — 返回数据库表列表
- `GET /api/reports` — 返回报表目录
- `GET /api/sql-definitions` — 返回看板 SQL 定义

## Environment Variables

复制 `.env.example` 为 `.env` 并填入实际值：

```
DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME
LLM_PROVIDER=claude|qwen|deepseek
ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL
```
