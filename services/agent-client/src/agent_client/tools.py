"""MCP client setup and tool management."""

import logging
import os

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from shared.config import get_settings

logger = logging.getLogger(__name__)


def get_server_connections() -> dict:
    """Build MCP server connection config from environment."""
    settings = get_settings()
    # When running inside Docker, hostnames match service names.
    # When running locally, default to localhost.
    news_host = os.environ.get("NEWS_MCP_HOST", "news-mcp")
    pdf_host = os.environ.get("PDF_MCP_HOST", "pdf-mcp")
    price_host = os.environ.get("PRICE_MCP_HOST", "price-mcp")

    return {
        "news": {
            "transport": "sse",
            "url": f"http://{news_host}:{settings.news_mcp_port}/sse",
            "timeout": 60,
        },
        "pdf": {
            "transport": "sse",
            "url": f"http://{pdf_host}:{settings.pdf_mcp_port}/sse",
            "timeout": 120,
        },
        "price": {
            "transport": "sse",
            "url": f"http://{price_host}:{settings.price_mcp_port}/sse",
            "timeout": 60,
        },
    }


class MCPClientManager:
    """Manages lifecycle of the MultiServerMCPClient."""

    def __init__(self) -> None:
        self.client: MultiServerMCPClient | None = None
        self.tools: list[BaseTool] = []
        self._tool_by_name: dict[str, BaseTool] = {}

    async def connect(self) -> None:
        """Connect to all configured MCP servers and load tools."""
        connections = get_server_connections()
        logger.info("Connecting to MCP servers: %s", list(connections.keys()))
        self.client = MultiServerMCPClient(connections)
        self.tools = await self.client.get_tools()
        self._tool_by_name = {tool.name: tool for tool in self.tools}
        logger.info("Loaded %d tools: %s", len(self.tools), list(self._tool_by_name.keys()))

    async def close(self) -> None:
        """Close all MCP connections."""
        if self.client is not None:
            await self.client.__aexit__(None, None, None)
            self.client = None
            logger.info("MCP client closed")

    def get_tool(self, name: str) -> BaseTool:
        """Return a loaded tool by name."""
        if name not in self._tool_by_name:
            raise KeyError(f"Tool {name!r} not found. Available: {list(self._tool_by_name.keys())}")
        return self._tool_by_name[name]


# Global singleton used by the FastAPI lifespan.
mcps: MCPClientManager | None = None


def set_mcp_client(manager: MCPClientManager) -> None:
    """Set the global MCP client manager."""
    global mcps
    mcps = manager


def get_mcp_client() -> MCPClientManager:
    """Return the global MCP client manager."""
    if mcps is None:
        raise RuntimeError("MCP client has not been initialized")
    return mcps
