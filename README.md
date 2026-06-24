# 矿权日报 Agent

> 基于 **MCP（Model Context Protocol）+ LangGraph** 的矿业资产每日简报生成器。
>
> 输入一句自然语言需求（例如「生成一份关于 Pilbara 锂矿的今日简报」），Agent 会自动编排三个 MCP 工具服务——**新闻聚合、PDF 储量解析、金属价格行情**——并产出一份结构化 Markdown 简报：新闻摘要 / 储量数据 / 价格走势 / 风险提示 + 引用来源。

---

## 目录

- [它能做什么](#它能做什么)
- [架构](#架构)
- [快速开始](#快速开始)
- [数据模式：Mock 还是真实数据](#数据模式mock-还是真实数据)
- [使用方式](#使用方式)
  - [① 网页端](#-网页端推荐)
  - [② HTTP API](#-http-api)
- [配置](#配置)
- [在其他地方调用 MCP 服务](#在其他地方调用-mcp-服务)
  - [MCP 工具清单](#mcp-工具清单)
  - [方式 A：Claude Desktop / Cursor](#方式-aclaude-desktop--cursor)
  - [方式 B：Python MCP 客户端](#方式-bpython-mcp-客户端)
  - [方式 C：原始 SSE 协议](#方式-c原始-sse-协议)
  - [price-mcp 的额外 REST 配置接口](#price-mcp-的额外-rest-配置接口)
- [已知限制](#已知限制)
- [常用命令](#常用命令)

---

## 它能做什么

- 🗞 **新闻聚合**：按关键词搜索近期矿业新闻，可抓取单篇正文（Google News RSS / Currents API）。
- 📄 **PDF 储量解析**：下载并解析 NI 43-101 风格的技术报告，抽取 Measured / Indicated / Inferred 资源量表格（PyMuPDF + pdfplumber）。
- 📈 **金属价格行情**：查询商品现价与近 N 天走势（MetalpriceAPI）。
- 🤖 **Agent 编排**：LangGraph ReAct 图自动决定调用哪些工具、何时收尾，最终汇总成简报。
- 🌐 **开箱即用的网页端**：上传 PDF、对话生成简报、在线配置模型与价格 API。

> **零密钥即可体验**：`.env` 默认 `USE_MOCK=true`，无需任何 API Key 即可用内置 mock 数据跑通完整链路。

---

## 架构

```
                          浏览器 / curl / 其他客户端
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │  agent-client  :3000   │   FastAPI + LangGraph ReAct
                        │  （Agent 编排 + Web UI）│
                        └───────────┬───────────┘
                                    │  MCP over SSE（内部 Docker 网络）
                ┌───────────────────┼───────────────────┐
                ▼                   ▼                   ▼
      ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
      │ mining-news-mcp │ │ mineral-pdf-mcp │ │  lme-price-mcp  │
      │      :8000      │ │      :8001      │ │      :8002      │
      └────────┬────────┘ └────────┬────────┘ └────────┬────────┘
               ▼                   ▼                   ▼
   Google News RSS /        PyMuPDF +            MetalpriceAPI /
   Currents API / Mock      pdfplumber / Mock    Mock
```

- 四个服务都是独立容器，通过 `docker-compose.yml` 编排，挂在同一内部网络 `miner-net`。
- 三个 MCP 服务各自暴露标准的 **MCP SSE 端点**（`/sse` + `/messages`）和 `/health`，**可被任意 MCP 客户端独立调用**（见下文）。
- `agent-client` 既是浏览器入口，也是 MCP 客户端（用 `langchain-mcp-adapters` 连这三个服务）。

技术栈：Python 3.11 · FastAPI · LangGraph · FastMCP · Starlette/SSE · Docker Compose · 前端原生 JS + Tailwind(CDN)。

---

## 快速开始

**环境要求**：Docker ≥ 24，Docker Compose ≥ 2.20。

```bash
git clone <repo-url> miner
cd miner
cp .env.template .env          # 默认 USE_MOCK=true，无需填任何 Key
docker compose up --build -d
```

等待约 30 秒健康检查通过：

```bash
docker compose ps
```

浏览器打开 **http://localhost:3000** 即可。

---

## 数据模式：Mock 还是真实数据

> **重要 · 请先读这一节。** 本项目**默认以 Mock（示例）数据开箱即用**，方便零配置体验。
> **要拿到真实数据，使用者必须自行配置 key 并关闭全局 Mock。** 不配置 ≠ 报错，而是悄悄给你示例数据——所以请务必确认自己跑在哪个模式。

### 各工具对 key 的要求并不一样

| 工具服务 | 真实数据需要 | 不配置时的表现 |
|---|---|---|
| **lme-price-mcp**（金属价格） | `METALPRICE_API_KEY` — **必需** | 回退到 mock 价格 |
| **mining-news-mcp**（矿业新闻） | `CURRENTS_API_KEY` — **可选** | 走 Google News RSS，**仍是真实新闻**；留空也能用 |
| **mineral-pdf-mcp**（储量解析） | **无需任何 key** | 给一个真实 PDF URL 即真解析（PyMuPDF 本地） |

- **price 是硬要求**：没有 MetalpriceAPI key 就拿不到真实行情。
- **news 没那么硬**：Currents key 只是「更快/更全」的增强；留空会自动降级到免 key 的 Google News RSS，**输出的依然是真实新闻**。
- **pdf 根本没有 key**：它是本地解析，只要 `USE_MOCK=false` 并给真实 PDF 链接就真解析。

> 注：免费版 MetalpriceAPI 仅覆盖金/银/铂/钯；铜/镍/锂等基本金属不在免费套餐内，查询时会单独回退到 mock。详见[已知限制](#已知限制)。

### 开启真实数据：在 `.env` 中配置（部署者操作）

```bash
USE_MOCK=false                 # 总开关：关闭全局 Mock —— 这是开启真实数据的前提
METALPRICE_API_KEY=你的key      # price 必填，否则该项回退 mock
CURRENTS_API_KEY=              # news 选填，留空走 Google News RSS（仍真实）
# pdf 无需任何 key
```

改完 `docker compose up -d` 重启即可。两种模式的完整行为：

- `USE_MOCK=true`（默认）：**所有**工具一律返回 mock，无需任何 key，适合纯演示。
- `USE_MOCK=false`：各工具各自尝试真实数据 —— price 没 key 时单独回退 mock、news 自动降级到 RSS、pdf 直接真解析。

> price-mcp 还额外支持**运行时配置**（网页 ⚙️ 弹窗 / REST 接口，见[下文](#price-mcp-的额外-rest-配置接口)）：在那里配了 key，即使全局 `USE_MOCK=true` 也会让 price 走真实数据；news/pdf 暂无此热配置，只认全局 `USE_MOCK`。

---

## 使用方式

### ① 网页端（推荐）

打开 http://localhost:3000：

1. **对话生成简报**：在底部输入框输入需求（如「生成一份关于必和必拓铜矿的今日简报」）→ 发送。
2. **上传 PDF 储量报告**：左侧「文件交付」上传 NI 43-101 PDF，或用对话框的 📎 作为附件；附件会作为独立记忆点，在后续对话中持续可用。
3. **下载简报**：左侧「下载最新简报」导出 Markdown。
4. **⚙️ 模型配置**：右上角弹窗中在线配置 LLM 与金属价格 API（见[配置](#配置)）。

> ⚠️ Demo 对话保存在内存中，未做持久化，刷新或重启后丢失。

### ② HTTP API

生成简报：

```bash
curl -X POST http://localhost:3000/briefing \
  -H "Content-Type: application/json" \
  -d '{"query": "给我生成一份关于 Pilbara 锂矿的今日简报"}'
```

返回：

```json
{
  "query": "...",
  "markdown": "# 矿权日报：...",
  "cached": false
}
```

主要端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/briefing` | 生成简报（body：`{query, attachments?}`） |
| `POST` | `/api/upload/pdf` | 上传并解析 PDF（multipart）|
| `GET`  | `/api/download/briefing` | 下载最近一次简报（Markdown）|
| `GET/POST` | `/api/config/llm` | 读取 / 更新 LLM 配置 |
| `GET/POST` | `/api/config/price` | 读取 / 更新价格 API 配置（代理到 price-mcp）|
| `GET`  | `/health` | 健康检查 |

> 提示：相同请求 30 分钟内命中缓存（返回 `cached: true`），节省 token；相同 PDF 按内容哈希复用解析结果。

---

## 配置

所有配置都可以**两种方式**设置，运行时配置（网页/SQLite）优先于环境变量：

**A. 网页端**（推荐，无需重启）：右上角 ⚙️ → 填 LLM 与金属价格 API → 保存 / 测试连接。

**B. `.env` 文件**（重启生效）：

```bash
USE_MOCK=true                  # true=全程 mock，无需任何 Key
LLM_PROVIDER=openai            # openai | anthropic | openai-compatible
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
ANTHROPIC_API_KEY=
CURRENTS_API_KEY=              # 新闻源（可选，不填用 Google News RSS / mock）
METALPRICE_API_KEY=            # 价格源（可选，不填用 mock）
```

> 运行时配置存放在 `data/llm_config.db` 与 `data/price_config.db`（SQLite，已 `.gitignore`，密钥不会进版本库）。

---

## 在其他地方调用 MCP 服务

三个 MCP 服务遵循标准 MCP 协议、通过 **SSE 传输**暴露，**可脱离本 Agent 被任何 MCP 客户端调用**。端口（宿主机）：

> ⚠️ **调用前请先配置 key。** 这些 MCP 默认运行在 Mock 模式（`USE_MOCK=true`），直接连上去会拿到**示例数据**。要拿真实数据，请按[数据模式](#数据模式mock-还是真实数据)在部署该容器的 `.env` 中设 `USE_MOCK=false` 并填好对应 key（至少 `METALPRICE_API_KEY`）。配置发生在**部署 MCP 的人**手里，不在调用方手里。

| 服务 | 端口 | SSE 端点 | 工具 |
|------|------|----------|------|
| `mining-news-mcp` | 8000 | `http://localhost:8000/sse` | `search`, `fetch_article` |
| `mineral-pdf-mcp` | 8001 | `http://localhost:8001/sse` | `extract_resources` |
| `lme-price-mcp`   | 8002 | `http://localhost:8002/sse` | `get_price`, `get_trend` |

### MCP 工具清单

```text
# mining-news-mcp
search(query: str, days: int = 7) -> list[dict]
    搜索近期矿业新闻。返回 [{title, source, published, summary, url}, ...]

fetch_article(url: str) -> dict
    抓取单篇新闻正文。返回 {title, content, source, url}

# mineral-pdf-mcp
extract_resources(pdf_url: str) -> dict
    下载并解析 NI 43-101 PDF 储量表。返回 {deposit, commodity, tables, notes}
    （tables 为 [{headers, rows}, ...]）

# lme-price-mcp
get_price(commodity: str, date: str | None = None) -> dict
    查询某商品现价/历史价。返回 {date, price, currency, unit, benchmark}
    commodity 例：gold, silver, platinum, palladium, copper, nickel, aluminium...

get_trend(commodity: str, days: int = 30) -> list[dict]
    查询近 N 天走势。返回 [{date, price, currency, unit}, ...]
```

### 方式 A：Claude Desktop / Cursor

仓库根目录的 `mcp-config.json` 即可直接使用：

```json
{
  "mcpServers": {
    "mining-news-mcp": { "url": "http://localhost:8000/sse" },
    "mineral-pdf-mcp": { "url": "http://localhost:8001/sse" },
    "lme-price-mcp":   { "url": "http://localhost:8002/sse" }
  }
}
```

将其内容合并到：

- **Claude Desktop**：`%APPDATA%\Claude\claude_desktop_config.json`（Windows）/ `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）
- **Cursor**：`~/.cursor/mcp.json`

重启后即可在对话里直接驱动这些工具，例如：

> 「用 lme-price-mcp 查 lithium 近 30 天走势」
> 「用 mineral-pdf-mcp 解析这个 PDF 的储量：<pdf_url>」

### 方式 B：Python MCP 客户端

用 `langchain-mcp-adapters`（本项目 agent-client 同款方式）把工具接进任意 LangChain/LangGraph 应用：

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "news":  {"url": "http://localhost:8000/sse", "transport": "sse"},
    "pdf":   {"url": "http://localhost:8001/sse", "transport": "sse"},
    "price": {"url": "http://localhost:8002/sse", "transport": "sse"},
})

tools = await client.get_tools()          # 拿到可直接 bind 到 LLM 的工具列表
# 或调用底层 session：
price = await client.session("price")      # 视适配器版本而定
```

或用官方 `mcp` SDK 直接连单个服务：

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async with sse_client("http://localhost:8002/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("get_price", {"commodity": "gold"})
        print(result)
```

### 方式 C：原始 SSE 协议

MCP over SSE 的底层约定（无 SDK 时也可对接）：

- `GET  /sse`：建立 SSE 长连接，服务器先推送一条 `endpoint` 事件，给出带 `session_id` 的回信地址。
- `POST /messages?session_id=...`：客户端把 JSON-RPC 请求（`initialize` / `tools/list` / `tools/call`）POST 到该地址，结果经 SSE 通道异步返回。

> 一般直接用方式 A/B 的 SDK 即可，无需手写协议。

### price-mcp 的额外 REST 配置接口

除 MCP 工具外，`lme-price-mcp` 还暴露一组普通 HTTP 接口用于运行时配置（被 agent-client 代理）：

```text
GET  /config/price        # 读取当前价格 API 配置（key 掩码）
POST /config/price        # 更新 {provider, base_url, api_key, use_mock}
POST /config/price/test   # 用当前配置做一次真实探测
```

---

## 已知限制

- **默认 Mock**：开箱默认 `USE_MOCK=true`，所有工具返回示例数据；要真实数据须显式配置（见[数据模式](#数据模式mock-还是真实数据)）。
- **Mock 回退**：即便 `USE_MOCK=false`，当某商品不在价格源套餐内（如 MetalpriceAPI 免费版仅支持金/银/铂/钯，铜/镍/锂不支持），price 仍会自动回退到 mock 数据。
- **news/pdf 无热配置**：price-mcp 支持网页/REST 运行时改 key，news-mcp、pdf-mcp 目前只认启动时的全局 `USE_MOCK` 与环境变量。
- **缓存**：简报与 PDF 解析结果走内存 TTL 缓存（30 分钟），进程重启即失效。
- **对话无持久化**：网页对话仅存内存，刷新/重启丢失。
- **Token 统计为估算**：用 tiktoken 近似计算，OpenAI-compatible 模型（如 DeepSeek）仅供参考。
- **反复上限**：Agent 默认最多 6 轮工具调用（`MAX_TOOL_ITERATIONS`），到顶强制收尾，避免弱模型死循环。

---

## 常用命令

```bash
make start    # docker compose up --build -d
make stop     # docker compose down
make logs     # 跟踪日志
make demo     # 强制 mock 模式启动
make test     # 调用 /briefing 冒烟测试
make clean    # 删除容器与卷
```

---

*本项目为演示性质（Demo），用于展示 MCP 工具链 + LangGraph Agent 编排，不构成任何投资建议。*
