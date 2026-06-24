"""LLM setup for the agent, including a deterministic mock LLM for demo mode."""

import json
import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from shared.config import Settings, get_settings

from agent_client.config_store import LLMConfig, get_llm_config

logger = logging.getLogger(__name__)


def create_llm(settings: Settings | None = None, config: LLMConfig | None = None) -> BaseChatModel:
    """Create the LLM client based on runtime config and environment.

    Priority:
    1. Runtime config (saved via the web UI / config API).
    2. Environment variables from ``.env``.
    3. Deterministic MockLLM when nothing is configured.
    """
    settings = settings or get_settings()
    config = config or get_llm_config()

    if config.use_mock:
        logger.info("Runtime config requests mock LLM")
        return MockLLM()

    provider = (config.provider or settings.llm_provider or "openai").lower()

    # 1. Runtime configuration takes precedence.
    if config.api_key:
        api_key = config.api_key
        if api_key:
            model = config.model or (
                settings.openai_model if provider in ("openai", "openai-compatible") else settings.anthropic_model
            )
            if provider == "anthropic":
                logger.info("Using Anthropic model %s via runtime config", model)
                kwargs: dict = {
                    "model": model,
                    "anthropic_api_key": api_key,
                    "temperature": 0.2,
                    "max_tokens": 4096,
                }
                if config.base_url:
                    kwargs["anthropic_api_url"] = config.base_url
                return ChatAnthropic(**kwargs)

            logger.info("Using OpenAI-compatible model %s (base_url=%s)", model, config.base_url)
            kwargs = {
                "model": model,
                "api_key": api_key,
                "temperature": 0.2,
            }
            if config.base_url:
                kwargs["base_url"] = config.base_url
            return ChatOpenAI(**kwargs)

    # 2. Demo/fallback: when USE_MOCK=true and no runtime credentials, avoid calling any real API.
    if settings.use_mock:
        logger.info("USE_MOCK=true and no runtime LLM credentials; using mock LLM")
        return MockLLM()

    # 3. Fall back to environment-based keys.
    if provider == "anthropic":
        if settings.anthropic_api_key:
            logger.info("Using Anthropic model %s", settings.anthropic_model)
            return ChatAnthropic(
                model=settings.anthropic_model,
                anthropic_api_key=settings.anthropic_api_key,
                temperature=0.2,
                max_tokens=4096,
            )
        logger.warning("ANTHROPIC_API_KEY not set; falling back to mock LLM")
        return MockLLM()

    if settings.openai_api_key:
        logger.info("Using OpenAI model %s", settings.openai_model)
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.2,
        )

    logger.warning("No LLM API key configured; falling back to mock LLM")
    return MockLLM()


async def test_llm_connection(config: LLMConfig) -> dict:
    """Try a single LLM call with the supplied config and report success/failure."""
    try:
        llm = create_llm(config=config)
        if isinstance(llm, MockLLM):
            return {"ok": True, "mode": "mock", "message": "当前为 Mock LLM 模式"}

        response = await llm.ainvoke([HumanMessage(content="Say OK")])
        content = response.content if isinstance(response.content, str) else str(response.content)
        return {
            "ok": True,
            "mode": "real",
            "message": content.strip()[:200] or "连接成功",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM connection test failed: %s", exc)
        return {"ok": False, "mode": "error", "message": f"连接失败：{exc}"}


class MockLLM(BaseChatModel):
    """Deterministic LLM substitute that drives the demo workflow.

    First call returns tool calls for news, pdf and price tools.
    Second call formats the tool outputs into the required Markdown briefing.
    """

    def _llm_type(self) -> str:
        return "mock"

    def bind_tools(self, tools):
        """Allow tool binding; mock ignores the actual tool list."""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ARG002
        raise NotImplementedError("Use invoke/ainvoke")

    def _convert_message_to_dict(self, message):
        return {"role": "assistant", "content": message.content}

    def invoke(self, input_messages, config=None, **kwargs):  # noqa: ARG002
        """Return deterministic assistant messages."""
        messages = input_messages if isinstance(input_messages, list) else input_messages.messages

        # Check if we already have tool results
        tool_results = [m for m in messages if isinstance(m, ToolMessage)]
        if tool_results:
            content = self._format_answer(messages)
            return AIMessage(content=content)

        # First turn: request tool calls
        tool_calls = [
            {
                "id": "call_search",
                "name": "search",
                "args": {"query": "Pilbara lithium", "days": 7},
            },
            {
                "id": "call_extract_resources",
                "name": "extract_resources",
                "args": {"pdf_url": "https://example.com/pilgangoora-ni43-101.pdf"},
            },
            {
                "id": "call_get_trend",
                "name": "get_trend",
                "args": {"commodity": "lithium", "days": 30},
            },
        ]
        return AIMessage(content="", tool_calls=tool_calls)

    def _format_answer(self, messages) -> str:
        """Build a Markdown briefing from tool results in the message history."""
        news_items = []
        resources = None
        trend_points = []

        for msg in messages:
            if not isinstance(msg, ToolMessage):
                continue
            try:
                data = json.loads(msg.content)
            except json.JSONDecodeError:
                continue

            # MCP tools wrap results in TextContent-like list; unwrap if needed
            if isinstance(data, list) and data and isinstance(data[0], dict) and "text" in data[0]:
                try:
                    data = json.loads(data[0]["text"])
                except json.JSONDecodeError:
                    pass

            if msg.name == "search" and isinstance(data, list):
                news_items = data
            elif msg.name == "extract_resources" and isinstance(data, dict):
                resources = data
            elif msg.name == "get_trend" and isinstance(data, list):
                trend_points = data

        # News section
        news_md = "\n\n".join(
            f"- **{item.get('title', '无标题')}**：{item.get('summary', '')} "
            f"[来源]({item.get('url', '#')})"
            for item in news_items[:5]
        )

        # Resources section (natural-language summary, with an optional compact table)
        resources_md = "未获取到储量数据。"
        if resources and resources.get("tables"):
            table = resources["tables"][0]
            deposit = resources.get("deposit", "N/A")
            commodity = resources.get("commodity", "锂")
            headers = table.get("headers", [])
            rows = table.get("rows", [])

            # Build a sentence-style summary from the first column (category).
            summary_parts = []
            for row in rows:
                if not row:
                    continue
                category = str(row[0]).strip()
                if category.lower() in {"measured", "indicated", "inferred", "total", "m+i", "m+i+i"}:
                    summary_parts.append(
                        f"{category} 资源量约 {row[1]}，品位约 {row[2]}"
                    )

            if summary_parts:
                resources_md = (
                    f"**矿床**：{deposit}（{commodity}）。根据 NI 43-101 报告，"
                    f"{'；'.join(summary_parts)}。"
                )
            else:
                # Fallback to a compact table if rows are not in expected shape.
                header_line = " | ".join(headers)
                row_lines = "\n".join(" | ".join(row) for row in rows)
                resources_md = (
                    f"**矿床**：{deposit}（{commodity}）\n\n"
                    f"| {header_line} |\n"
                    f"| {' | '.join(['---'] * len(headers))} |\n"
                    f"{row_lines}\n\n"
                )
            resources_md += f"\n\n*{resources.get('notes', '')}*"

        # Trend section
        trend_md = "未获取到价格走势。"
        if trend_points:
            start = trend_points[0]
            end = trend_points[-1]
            trend_md = (
                f"近 {len(trend_points)} 个交易日，锂价从 {start.get('price')} "
                f"{start.get('currency')}/{start.get('unit')} 波动至 "
                f"{end.get('price')} {end.get('currency')}/{end.get('unit')}。"
                f"整体呈现窄幅震荡态势，短期需关注 Pilbara BMX 拍卖结果及中国下游补库节奏。"
            )

        return f"""## 新闻摘要
{news_md or "暂无新闻。"}

## 储量数据
{resources_md}

## 价格走势
{trend_md}

## 风险提示
1. **市场风险**：锂价仍受电动车需求增速及碳酸锂库存周期影响，短期价格波动较大。
2. **政策风险**：主要消费国（中国、欧美）新能源补贴及关税政策变化可能影响需求预期。
3. **地质/资源风险**：储量估算基于历史钻探数据，实际可采储量需以最新 NI 43-101 报告为准。
4. **ESG 风险**：西澳矿区水资源、原住民权益及尾矿管理是投资者关注的重点。

*注：当前为 Mock LLM 模式，仅用于演示 Agent 编排与 MCP 工具链路。*
"""
