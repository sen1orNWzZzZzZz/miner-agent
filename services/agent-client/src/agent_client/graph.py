"""LangGraph definition for the briefing agent."""

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from agent_client.nodes import (
    agent_node,
    format_node,
    should_continue,
    summarize_pdf_node,
    tools_node,
)
from agent_client.state import AgentState


def build_graph():
    """Build and compile the ReAct-style briefing graph."""
    builder = StateGraph(AgentState)

    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)
    builder.add_node("summarize_pdf", summarize_pdf_node)
    builder.add_node("format", format_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "format": "format"},
    )

    def route_after_tools(state: AgentState) -> str:
        """If the last tool batch parsed a PDF, summarize it before the next agent turn."""
        for msg in reversed(state["messages"]):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                names = {call.get("name") for call in msg.tool_calls}
                return "summarize_pdf" if "extract_resources" in names else "agent"
        return "agent"

    builder.add_conditional_edges(
        "tools",
        route_after_tools,
        {"summarize_pdf": "summarize_pdf", "agent": "agent"},
    )
    builder.add_edge("summarize_pdf", "agent")
    builder.add_edge("format", END)

    return builder.compile()
