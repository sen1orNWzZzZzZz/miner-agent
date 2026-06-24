"""LangGraph state definitions."""

import operator
from typing import Annotated, TypedDict


def _replace_list(_old: list, new: list) -> list:
    """Reducer that replaces the previous list with the new one.

    This lets nodes return the full updated attachments list, including removals.
    """
    return new


class AgentState(TypedDict):
    """State carried through the briefing graph."""

    messages: Annotated[list, operator.add]
    sources: Annotated[list, operator.add]
    query: str
    markdown: str | None
    pdf_summary: str | None
    attachments: Annotated[list[str], _replace_list]
    prompt_tokens: Annotated[int, operator.add]
    completion_tokens: Annotated[int, operator.add]
    total_tokens: Annotated[int, operator.add]
    iterations: Annotated[int, operator.add]
