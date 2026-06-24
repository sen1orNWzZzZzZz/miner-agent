"""LangGraph nodes for the briefing agent."""

import json
import logging
import os
import re
from typing import Any, cast

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END

from agent_client.cache import pdf_cache, pdf_cache_key
from agent_client.config_store import get_llm_config
from agent_client.llm import MockLLM, create_llm
from agent_client.state import AgentState
from agent_client.token_counter import count_messages, count_text
from agent_client.tools import get_mcp_client
from shared.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是"矿权日报"智能分析师，专门生成矿业资产每日简报。

你的任务：根据用户query，调用可用工具收集信息，并输出一份结构化的 Markdown 简报。

简报必须包含以下四个部分（使用二级标题 ##）：
1. ## 新闻摘要：总结最新矿业新闻（3-5 条要点），每条要点后标注来源链接 `[来源](url)`。
2. ## 储量数据：基于 PDF 解析得到的资源量表，用自然语言总结核心资源量（Measured / Indicated / Inferred）。说明矿床名、矿种、各级别吨位与品位、总资源量等关键数字，并注明来源 PDF 链接。可以附一张精简的 Markdown 表格作为补充，但主体必须是段落化描述，不要直接复制原始表格。
3. ## 价格走势：分析近 30 天价格走势，给出关键价格水平和趋势判断。
4. ## 风险提示：列出市场、政策、地质、ESG 等方面的主要风险。

可用工具：
- mining-news-mcp.search(query, days)：搜索矿业新闻。
- mining-news-mcp.fetch_article(url)：获取单篇新闻全文。
- mineral-pdf-mcp.extract_resources(pdf_url)：解析 NI 43-101 PDF 储量报告。
- lme-price-mcp.get_price(commodity, date)：获取商品价格。
- lme-price-mcp.get_trend(commodity, days)：获取价格走势。

注意：
- 优先使用搜索获取最新新闻；如需了解某篇新闻细节，再调用 fetch_article。
- 可以在一次回复中**并行调用多个相互独立的工具**（例如同时 search 和 get_trend），以减少轮次、加快生成。
- **不要重复调用已经成功返回结果的工具**；相同参数的工具只调用一次。
- 一旦四个部分所需的信息基本齐全，就**立即停止调用工具并输出最终 Markdown 简报**，不要为了完美而无限收集。
- 若 PDF URL 未知，可使用搜索工具查找 "NI 43-101 Pilgangoora technical report pdf" 等关键词。
- 若用户已上传 PDF 附件（会在 system 消息中列出附件 URL），可优先调用 extract_resources 解析这些附件。
- 当收到 extract_resources 的表格数据后，应像矿业分析师一样先进行自然语言总结，再输出；不要直接罗列原始单元格。
- 所有数据必须标注来源；若使用 mock 数据，请明确说明。
- 最终回答必须为 Markdown 格式，不要输出 JSON 或代码块包裹。
"""

# Hard cap on agent⇄tools ReAct rounds. On reaching it the agent is forced to
# produce a final briefing without tools, guaranteeing graceful termination
# instead of looping until LangGraph's recursion limit raises.
MAX_TOOL_ITERATIONS = int(os.environ.get("MAX_TOOL_ITERATIONS", "6"))

# Sliding window over conversation history. A single briefing starts from a
# fresh state (one HumanMessage), so this should be large enough never to trim
# the agent's own tool results mid-loop — otherwise it "forgets" what it already
# fetched and re-calls the same tools forever. The iteration cap above bounds
# real growth; this only guards against pathological histories.
MAX_CONTEXT_MESSAGES = int(os.environ.get("MAX_CONTEXT_MESSAGES", "40"))


def _build_attachment_context(attachments: list[str]) -> str:
    """Build a system-message fragment listing uploaded PDF attachments."""
    if not attachments:
        return ""
    lines = ["用户已上传以下 PDF 附件，可供解析："]
    for filename in attachments:
        url = _public_url(f"http://agent-client:3000/api/files/{os.path.basename(filename)}")
        lines.append(f"- {os.path.basename(filename)}: {url}")
    lines.append("如需要储量分析，请调用 extract_resources 解析上述 PDF URL。")
    return "\n".join(lines)


def _trim_messages(messages: list, max_count: int = MAX_CONTEXT_MESSAGES) -> list:
    """Apply a sliding window to conversation messages.

    Keeps the most recent ``max_count`` messages while always preserving the
    very first message (the original user query) so the agent never loses sight
    of the task. If the first kept tail message is an orphan ToolMessage, it is
    dropped to avoid confusing the LLM.
    """
    if len(messages) <= max_count:
        return messages
    head = messages[:1]
    tail = messages[-(max_count - 1):]
    while tail and isinstance(tail[0], ToolMessage):
        tail = tail[1:]
    return head + tail


def agent_node(state: AgentState) -> dict:
    """Call the LLM with tool binding to decide next action."""
    mcp = get_mcp_client()

    iterations = state.get("iterations", 0)
    force_final = iterations >= MAX_TOOL_ITERATIONS

    llm = create_llm()
    if force_final:
        # When we hit the tool-call cap we still need the model to ignore the
        # tools. For OpenAI-compatible models, tool_choice="none" is the API-level
        # signal that keeps the model from emitting raw tool-call syntax.
        try:
            llm = llm.bind_tools(mcp.tools, tool_choice="none")
        except TypeError:
            llm = llm.bind_tools(mcp.tools)
        logger.info("Reached tool-call cap (%d); forcing final briefing", MAX_TOOL_ITERATIONS)
    else:
        llm = llm.bind_tools(mcp.tools)

    attachment_context = _build_attachment_context(state.get("attachments", []))
    system_content = SYSTEM_PROMPT
    if attachment_context:
        system_content += "\n\n" + attachment_context
    if force_final:
        system_content += (
            "\n\n（已达到工具调用上限：请**不要再调用任何工具**，"
            "立即基于已收集到的信息输出完整的最终 Markdown 简报。"
            "若某部分信息缺失，请如实说明，不要再尝试获取。）"
        )

    trimmed_messages = _trim_messages(state["messages"], MAX_CONTEXT_MESSAGES)
    messages = [SystemMessage(content=system_content)] + trimmed_messages

    response = llm.invoke(messages)

    config = get_llm_config()
    if isinstance(llm, MockLLM) or config.use_mock:
        prompt_tokens = completion_tokens = 0
    else:
        prompt_tokens = count_messages(messages, config.model)
        completion_tokens = count_text(
            response.content if isinstance(response.content, str) else str(response.content),
            config.model,
        )

    logger.info("Agent produced %d tool call(s)", len(response.tool_calls) if hasattr(response, "tool_calls") else 0)
    return {
        "messages": [response],
        "iterations": 1,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


async def tools_node(state: AgentState) -> dict:
    """Execute tool calls in parallel and capture source metadata."""
    mcp = get_mcp_client()
    last_message = cast(AIMessage, state["messages"][-1])
    tool_calls = last_message.tool_calls or []

    if not tool_calls:
        return {"messages": [], "sources": []}

    messages: list[ToolMessage] = []
    sources: list[dict] = []

    for call in tool_calls:
        tool_name = call["name"]
        tool_args = call["args"]
        tool_call_id = call["id"]
        logger.info("Calling tool %s with args %r", tool_name, tool_args)

        # PDF extraction is expensive; serve from the shared TTL cache when the
        # same PDF (by content hash) was parsed recently.
        result = None
        cache_key = None
        cache_hit = False
        if tool_name == "extract_resources":
            cache_key = pdf_cache_key(tool_args.get("pdf_url", ""))
            cached = pdf_cache.get(cache_key)
            if cached is not None and cached.get("result") is not None:
                result = cached["result"]
                cache_hit = True
                logger.info("PDF extraction cache hit: %s", cache_key)

        if result is None:
            try:
                tool = mcp.get_tool(tool_name)
                result = await tool.ainvoke(tool_args)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Tool %s failed", tool_name)
                result = {"error": str(exc)}

            # Convert internal Docker URLs in PDF extraction results to public URLs
            # so the LLM and final citations produce clickable links for the user.
            if tool_name == "extract_resources":
                unwrapped = _unwrap_result(result)
                if isinstance(unwrapped, dict):
                    unwrapped["pdf_url"] = _public_url(unwrapped.get("pdf_url", ""))
                    result = unwrapped
                # Cache successful extractions for reuse within the TTL window.
                if cache_key and not (isinstance(result, dict) and result.get("error")):
                    existing = pdf_cache.get(cache_key) or {}
                    pdf_cache.set(cache_key, {**existing, "result": result})

        # Normalize result to string for the LLM
        if isinstance(result, str):
            content = result
        else:
            content = json.dumps(result, ensure_ascii=False, default=str)

        messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))
        sources.append(
            {
                "tool": tool_name,
                "args": tool_args,
                "result": result,
                "cached": cache_hit,
            }
        )

    return {"messages": messages, "sources": sources}


def should_continue(state: AgentState) -> str:
    """Route: continue if the LLM requested tool calls, otherwise format."""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "format"


async def summarize_pdf_result(result: Any, pdf_url: str) -> tuple[str, int, int]:
    """Ask the LLM to summarize extracted PDF resource tables in natural language.

    This treats PDF parsing as a one-off extraction and delegates the analyst-style
    summary to the agent/LLM, so the final briefing reads in plain language rather
    than raw table cells.

    Returns a ``(summary, prompt_tokens, completion_tokens)`` tuple so callers can
    account for the token cost of the summarization step.
    """
    result = _unwrap_result(result)
    deposit = result.get("deposit", "") if isinstance(result, dict) else ""
    commodity = result.get("commodity", "") if isinstance(result, dict) else ""
    tables = result.get("tables", []) if isinstance(result, dict) else []

    if not tables:
        return "未能从该 PDF 中抽取到资源量表格。", 0, 0

    llm = create_llm()
    if isinstance(llm, MockLLM):
        # Deterministic mock summary; avoids asking the mock LLM for a generic answer.
        table = tables[0]
        rows = table.get("rows", [])
        summary = (
            f"Mock 总结：{deposit or '该矿床'}（{commodity or '未知矿种'}）"
            f"共抽取到 {len(rows)} 行资源量数据，供演示使用。"
        )
        return summary, 0, 0

    prompt = f"""你是一位矿业储量分析师。下面是从一份 NI 43-101 风格 PDF 报告中抽取出的资源量表格。

请用一段自然语言中文总结核心储量信息，要求：
- 说明矿床名称、矿种；
- 分别概述 Measured、Indicated、Inferred 的吨位与品位（如有）；
- 给出总资源量或关键结论；
- 提及数据来源 PDF。

PDF URL: {pdf_url}
矿床：{deposit or "未知"}
矿种：{commodity or "未知"}

表格数据：
{json.dumps(tables, ensure_ascii=False, indent=2)[:4000]}

请只输出总结段落，不要输出原始表格，也不要加任何标题。"""

    messages = [SystemMessage(content=prompt)]
    response = await llm.ainvoke(messages)
    summary = response.content if isinstance(response.content, str) else str(response.content)
    summary = summary.strip()

    config = get_llm_config()
    prompt_tokens = count_messages(messages, config.model)
    completion_tokens = count_text(summary, config.model)
    return summary, prompt_tokens, completion_tokens


async def summarize_pdf_node(state: AgentState) -> dict:
    """Generate a natural-language summary of the most recent PDF extraction.

    The summary is injected back into the conversation as context so the final
    agent turn can produce a fluent, analyst-style reserves section.
    """
    pdf_sources = [s for s in state.get("sources", []) if s.get("tool") == "extract_resources"]
    if not pdf_sources:
        return {"pdf_summary": None, "messages": []}

    source = pdf_sources[-1]
    pdf_url = source.get("args", {}).get("pdf_url", "")
    summary, prompt_tokens, completion_tokens = await summarize_pdf_result(
        source.get("result"), _public_url(pdf_url)
    )
    return {
        "pdf_summary": summary,
        "messages": [SystemMessage(content=f"PDF 储量报告自然语言总结：{summary}")],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _unwrap_result(result: Any) -> Any:
    """Unwrap MCP TextContent list wrapper if present."""
    if (
        isinstance(result, list)
        and result
        and isinstance(result[0], dict)
        and "text" in result[0]
    ):
        try:
            return json.loads(result[0]["text"])
        except json.JSONDecodeError:
            pass
    return result


def _public_url(url: str) -> str:
    """Convert internal Docker service URLs into publicly clickable links."""
    settings = get_settings()
    internal_base = f"http://agent-client:{settings.agent_port}"
    if url.startswith(internal_base):
        return settings.agent_public_base_url + url[len(internal_base):]
    return url


def _format_source(idx: int, source: dict) -> str:
    """Render a single source entry in natural language with clickable links."""
    tool = source["tool"]
    args = source.get("args", {})
    result = _unwrap_result(source.get("result", {}))

    if tool == "search":
        query = args.get("query", "")
        days = args.get("days", "")
        return f"{idx}. 新闻搜索：**“{query}”**（近 {days} 天）"

    if tool == "fetch_article":
        url = _public_url(args.get("url", ""))
        title = ""
        if isinstance(result, dict):
            title = result.get("title") or ""
        if title:
            return f"{idx}. 新闻原文：[{title}]({url})"
        return f"{idx}. 新闻原文：[{url}]({url})"

    if tool == "extract_resources":
        url = _public_url(args.get("pdf_url", ""))
        deposit = ""
        if isinstance(result, dict):
            deposit = result.get("deposit") or ""
        if deposit:
            return f"{idx}. PDF 储量报告：**{deposit}** — [{url}]({url})"
        return f"{idx}. PDF 储量报告：[{url}]({url})"

    if tool == "get_price":
        commodity = args.get("commodity", "")
        date = args.get("date") or "今日"
        price_info = ""
        if isinstance(result, dict) and "price" in result:
            price_info = (
                f"，价格 {result['price']} "
                f"{result.get('currency', 'USD')}/{result.get('unit', 'tonne')}"
            )
        return f"{idx}. 价格查询：**{commodity}**（{date}）{price_info}"

    if tool == "get_trend":
        commodity = args.get("commodity", "")
        days = args.get("days", "")
        anchor = ""
        if isinstance(result, list) and result:
            latest = result[-1]
            if isinstance(latest, dict) and "price" in latest:
                anchor = (
                    f"，最新 {latest['price']} "
                    f"{latest.get('currency', 'USD')}/{latest.get('unit', 'tonne')}"
                )
        return f"{idx}. 价格走势：**{commodity}**（近 {days} 天）{anchor}"

    return f"{idx}. **{tool}**：{args}"


def _publicize_links(markdown: str) -> str:
    """Rewrite internal Docker service URLs in final markdown to public URLs."""
    settings = get_settings()
    internal_base = f"http://agent-client:{settings.agent_port}"
    return markdown.replace(internal_base, settings.agent_public_base_url)


# Some models (e.g. DeepSeek) occasionally leak their internal tool-call special
# tokens into plain-text content, e.g. ``<｜DSML｜tool_calls> ... </｜DSML｜tool_calls>``
# (fullwidth ｜ = U+FF5C) or the ASCII ``<|...|>`` variant. Strip such blocks and
# any stray special-token tags from the final briefing so the user never sees them.
_TOOLCALL_BLOCK_RE = re.compile(
    r"<[｜|][^>]*?tool_calls>.*?</[｜|][^>]*?tool_calls>", re.DOTALL
)
_SPECIAL_TAG_RE = re.compile(r"</?[｜|][^>]*?>")


def _strip_tool_call_artifacts(text: str) -> str:
    """Remove leaked tool-call special-token markup from model output."""
    text = _TOOLCALL_BLOCK_RE.sub("", text)
    text = _SPECIAL_TAG_RE.sub("", text)
    return text.strip()


def format_node(state: AgentState) -> dict:
    """Format the final answer into the required Markdown briefing."""
    last_message = state["messages"][-1]
    answer = last_message.content if isinstance(last_message, AIMessage) else str(last_message)
    answer = _strip_tool_call_artifacts(answer)
    if len(answer.strip()) < 30:
        answer = (
            "_模型未能基于已收集的信息生成完整正文（可能是工具调用次数已达上限或模型能力有限）。"
            "以下为已获取的引用来源，可据此人工补充，或更换更强的模型后重试。_"
        )

    sources = state.get("sources", [])
    seen = set()
    unique_sources = []
    for source in sources:
        args = source.get("args", {})
        key = args.get("url") or args.get("pdf_url") or json.dumps(args, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique_sources.append(source)

    sources_section = "\n".join(
        _format_source(i, source) for i, source in enumerate(unique_sources, 1)
    )

    prompt_tokens = state.get("prompt_tokens", 0)
    completion_tokens = state.get("completion_tokens", 0)
    total_tokens = state.get("total_tokens", 0)

    markdown = f"""# 矿权日报：{state['query']}

{answer}

---

## 引用来源
{sources_section or "*未收集到外部来源。*"}

---

**Token 统计**：输入 ~{prompt_tokens} / 输出 ~{completion_tokens} / 总计 ~{total_tokens}（tiktoken 估算，仅供参考）
"""
    markdown = _publicize_links(markdown)
    return {"messages": [AIMessage(content=markdown)], "markdown": markdown}
