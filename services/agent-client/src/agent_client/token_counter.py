"""Token counting utilities using tiktoken.

Provides approximate token counts for OpenAI-compatible and Anthropic models.
For unknown models (e.g. DeepSeek), falls back to the cl100k_base encoding.
"""

import logging

import tiktoken
from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


def get_encoder(model: str | None = None) -> tiktoken.Encoding:
    """Return a tiktoken encoder for the given model.

    Falls back to cl100k_base when the model is unknown or not specified.
    """
    model = model or "gpt-4o-mini"
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        logger.debug("Model %s not known to tiktoken, falling back to cl100k_base", model)
        return tiktoken.get_encoding("cl100k_base")


def count_text(text: str | None, model: str | None = None) -> int:
    """Count tokens in a plain text string."""
    if not text:
        return 0
    encoder = get_encoder(model)
    return len(encoder.encode(text))


def count_messages(messages: list[BaseMessage], model: str | None = None) -> int:
    """Approximate token count for a list of LangChain messages.

    This is a simple sum of the content lengths; it does not include the
    per-message overhead used by the official tokenizers, so it is a lower-bound
    estimate suitable for demo dashboards.
    """
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        total += count_text(content, model)
    return total
