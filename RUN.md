# 矿权日报 Agent — 5 分钟跑起来

## 环境要求

- Docker >= 24.0
- Docker Compose >= 2.20
- （可选）OpenAI API Key 或 Anthropic API Key
- （可选）Currents API Key / Metals-API Key（用于真实数据源）

## 1. 拉取并启动

```bash
git clone <repo-url> miner
cd miner
cp .env.template .env
# 默认 USE_MOCK=true，无需填写任何 Key 即可运行
docker compose up --build -d
```

等待约 30 秒，所有服务健康检查通过后：

```bash
docker compose ps
```

## 2. 生成 Pilbara 锂矿简报

```bash
curl -X POST http://localhost:3000/briefing \
  -H "Content-Type: application/json" \
  -d '{"query": "给我生成一份关于 Pilbara 锂矿的今日简报"}'
```

返回 JSON：

```json
{
  "query": "给我生成一份关于 Pilbara 锂矿的今日简报",
  "markdown": "# 矿权日报：..."
}
```

## 3. 在 Claude Desktop / Cursor 中验证 MCP Server

1. 复制 `mcp-config.json` 的内容到：
   - **Claude Desktop**: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) 或 `%APPDATA%\Claude\claude_desktop_config.json` (Windows)
   - **Cursor**: `~/.cursor/mcp.json`
2. 重启 Claude Desktop / Cursor。
3. 在对话中询问：
   - `请使用 mining-news-mcp 搜索最近 7 天 Pilbara 锂矿新闻`
   - `请使用 mineral-pdf-mcp 解析这个 PDF 的储量: <pdf_url>`
   - `请使用 lme-price-mcp 查询 lithium 近 30 天价格走势`

## 4. 切换真实数据源（可选）

编辑 `.env`：

```bash
USE_MOCK=false
OPENAI_API_KEY=sk-...
CURRENTS_API_KEY=...
METALS_API_KEY=...
```

然后重启：

```bash
docker compose down
docker compose up --build -d
```

## 5. 常用命令

```bash
make start      # docker compose up --build -d
make stop       # docker compose down
make logs       # docker compose logs -f
make demo       # 强制 mock 模式启动
make test       # 测试 briefing 接口
make clean      # 删除容器与卷
```

## 端口说明

| 服务 | 端口 | 用途 |
|------|------|------|
| mining-news-mcp | 8000 | 新闻聚合 SSE + `/health` |
| mineral-pdf-mcp | 8001 | PDF 解析 SSE + `/health` |
| lme-price-mcp | 8002 | 价格行情 SSE + `/health` |
| agent-client | 3000 | Agent 编排 HTTP API + `/health` |

## 架构

```
User Query
    │
    ▼
agent-client (LangGraph ReAct)
    │
    ├──▶ mining-news-mcp  ──▶ Google News RSS / Currents API / Mock
    ├──▶ mineral-pdf-mcp  ──▶ PyMuPDF + pdfplumber / Mock
    └──▶ lme-price-mcp    ──▶ Metals-API / Mock
    │
    ▼
Markdown 简报（含新闻、储量、价格、风险、引用源）
```
