"""FastAPI entry point for the Agent client."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from agent_client.cache import (
    briefing_cache,
    briefing_cache_key,
    content_cache_key,
    pdf_cache,
)
from agent_client.config_store import LLMConfig, get_llm_config, update_llm_config
from agent_client.graph import build_graph
from agent_client.llm import test_llm_connection
from agent_client.nodes import _public_url, summarize_pdf_result
from agent_client.state import AgentState
from agent_client.tools import MCPClientManager, set_mcp_client
from shared.config import get_settings

logger = logging.getLogger(__name__)


class BriefingRequest(BaseModel):
    """Request body for /briefing."""

    query: str
    attachments: list[str] = Field(default_factory=list)


class BriefingResponse(BaseModel):
    """Response body for /briefing."""

    query: str
    markdown: str
    cached: bool = False


class LLMConfigPayload(BaseModel):
    """Payload for updating LLM configuration."""

    provider: str = Field(default="openai")
    model: str = Field(default="gpt-4o-mini")
    base_url: str | None = Field(default=None)
    api_key: str | None = Field(default=None)
    use_mock: bool = Field(default=False)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Initialize MCP client on startup and close on shutdown."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    manager = MCPClientManager()
    await manager.connect()
    set_mcp_client(manager)
    logger.info("Agent client ready")
    yield
    await manager.close()


app = FastAPI(
    title="矿权日报 Agent",
    description="LangGraph agent orchestrating MCP servers to generate mining briefings.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def disable_static_cache(request, call_next):
    """Disable browser caching for static assets during active development."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static") or path in ("/", "/index.html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# Static web UI (directory is created as part of the build/source tree).
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    """Serve the web UI."""
    return RedirectResponse(url="/static/index.html")


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "service": "agent-client"}


@app.get("/api/config/llm")
async def get_llm_config_endpoint() -> dict:
    """Return the current LLM configuration (API key masked)."""
    return get_llm_config().to_masked_dict()


@app.post("/api/config/llm")
async def update_llm_config_endpoint(payload: LLMConfigPayload) -> dict:
    """Update the runtime LLM configuration."""
    try:
        config = update_llm_config(payload.model_dump(exclude_unset=True))
        return config.to_masked_dict()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to save LLM config")
        raise HTTPException(status_code=400, detail=f"Invalid config: {exc}") from exc


@app.post("/api/config/llm/test")
async def test_llm_config_endpoint() -> dict:
    """Test the current LLM configuration with a simple prompt."""
    config = get_llm_config()
    return await test_llm_connection(config)


def _price_mcp_base_url() -> str:
    """Internal base URL of the price-mcp service on the Docker network."""
    settings = get_settings()
    host = os.environ.get("PRICE_MCP_HOST", "price-mcp")
    return f"http://{host}:{settings.price_mcp_port}"


@app.get("/api/config/price")
async def get_price_config_endpoint() -> dict:
    """Proxy: return the price-API config (key masked) from the price-mcp service."""
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{_price_mcp_base_url()}/config/price")
    return r.json()


@app.post("/api/config/price")
async def update_price_config_endpoint(payload: dict) -> dict:
    """Proxy: update the price-API config on the price-mcp service."""
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{_price_mcp_base_url()}/config/price", json=payload)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.json().get("detail", "保存失败"))
    return r.json()


@app.post("/api/config/price/test")
async def test_price_config_endpoint() -> dict:
    """Proxy: ask the price-mcp service to test its current price-API config."""
    import httpx

    async with httpx.AsyncClient(timeout=40) as client:
        r = await client.post(f"{_price_mcp_base_url()}/config/price/test")
    return r.json()


def _attachment_url(filename: str) -> str:
    """Build the internal URL that the PDF MCP server uses to fetch an uploaded file."""
    return f"http://agent-client:3000/api/files/{os.path.basename(filename)}"


@app.post("/briefing", response_model=BriefingResponse)
async def create_briefing(request: BriefingRequest) -> BriefingResponse:
    """Generate a mining daily briefing for the given query."""
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    logger.info("Generating briefing for query: %r", query)

    # Serve an identical recent request from the cache to save tokens/latency.
    cache_key = briefing_cache_key(query, request.attachments)
    cached_markdown = briefing_cache.get(cache_key)
    if cached_markdown is not None:
        logger.info("Briefing cache hit: %s", cache_key)
        return BriefingResponse(query=query, markdown=cached_markdown, cached=True)

    graph = build_graph()
    initial_state: AgentState = {
        "messages": [HumanMessage(content=query)],
        "sources": [],
        "query": query,
        "markdown": None,
        "pdf_summary": None,
        "attachments": request.attachments,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "iterations": 0,
    }

    # Backstop recursion limit: the agent_node iteration cap should normally
    # force finalization well before this, but keep it generous enough for a
    # full multi-tool briefing (agent + tools + summarize per round).
    recursion_limit = int(os.environ.get("GRAPH_RECURSION_LIMIT", "40"))

    try:
        final_state = await graph.ainvoke(
            initial_state, config={"recursion_limit": recursion_limit}
        )
    except GraphRecursionError as exc:
        logger.warning("Graph hit recursion limit: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Agent 调用工具次数过多仍未收敛，请简化需求或稍后重试。",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Graph invocation failed")
        raise HTTPException(status_code=500, detail=f"Agent failed: {exc}") from exc

    markdown = final_state.get("markdown") or final_state["messages"][-1].content

    # Persist the latest briefing so it can be downloaded later.
    try:
        data_dir = os.environ.get("AGENT_DATA_DIR", "/app/data")
        os.makedirs(data_dir, exist_ok=True)
        briefing_path = os.path.join(data_dir, "latest_briefing.md")
        with open(briefing_path, "w", encoding="utf-8") as f:
            f.write(markdown)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to persist briefing")

    briefing_cache.set(cache_key, markdown)
    return BriefingResponse(query=query, markdown=markdown, cached=False)


@app.post("/api/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)) -> dict:
    """Upload a PDF and extract mineral resource tables via the PDF MCP server."""
    from agent_client.tools import get_mcp_client

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid content type {file.content_type!r}; only application/pdf is accepted",
        )

    try:
        contents = await file.read()
        # Persist uploaded file so it can be referenced later.
        data_dir = os.environ.get("AGENT_DATA_DIR", "/app/data")
        uploads_dir = os.path.join(data_dir, "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        safe_name = os.path.basename(file.filename)
        path = os.path.join(uploads_dir, safe_name)
        with open(path, "wb") as f:
            f.write(contents)

        # The PDF MCP server runs in another container and reaches us via the
        # Docker compose service name on the internal network.
        public_url = f"http://agent-client:3000/api/files/{safe_name}"

        # Serve the same PDF (by content hash) from cache to save tokens/latency.
        cache_key = content_cache_key(contents)
        cached = pdf_cache.get(cache_key)
        if cached is not None and cached.get("result") is not None and cached.get("summary") is not None:
            logger.info("PDF upload cache hit: %s", cache_key)
            return {
                "filename": safe_name,
                "result": cached["result"],
                "summary": cached["summary"],
                "cached": True,
            }

        mcp = get_mcp_client()
        tool = mcp.get_tool("extract_resources")
        result = await tool.ainvoke({"pdf_url": public_url})

        # Treat the extraction as a one-off parse and have the agent summarize it
        # into natural language for the frontend.
        try:
            summary, _prompt_tokens, _completion_tokens = await summarize_pdf_result(
                result, _public_url(public_url)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("PDF summary generation failed: %s", exc)
            summary = ""

        # Cache the parsed result + summary so identical PDFs reuse this work.
        pdf_cache.set(cache_key, {"result": result, "summary": summary})

        return {"filename": safe_name, "result": result, "summary": summary, "cached": False}
    except Exception as exc:  # noqa: BLE001
        logger.exception("PDF upload/extraction failed")
        raise HTTPException(status_code=500, detail=f"PDF extraction failed: {exc}") from exc


@app.get("/api/uploads")
async def list_uploads() -> dict:
    """List uploaded PDF files that can be attached to a chat."""
    data_dir = os.environ.get("AGENT_DATA_DIR", "/app/data")
    uploads_dir = os.path.join(data_dir, "uploads")
    if not os.path.isdir(uploads_dir):
        return {"files": []}
    files = [f for f in os.listdir(uploads_dir) if f.lower().endswith(".pdf")]
    return {"files": files}


@app.get("/api/files/{filename}")
async def serve_uploaded_file(filename: str) -> FileResponse:
    """Serve an uploaded PDF so the PDF MCP server can fetch it by URL."""
    data_dir = os.environ.get("AGENT_DATA_DIR", "/app/data")
    path = os.path.join(data_dir, "uploads", os.path.basename(filename))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="application/pdf", filename=filename)


@app.get("/api/download/briefing")
async def download_briefing() -> FileResponse:
    """Download the most recently generated briefing as a Markdown file."""
    data_dir = os.environ.get("AGENT_DATA_DIR", "/app/data")
    path = os.path.join(data_dir, "latest_briefing.md")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No briefing has been generated yet")
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename="briefing.md",
    )


def main() -> None:
    """CLI entry point."""
    import uvicorn

    port = int(os.environ.get("AGENT_PORT", "3000"))
    uvicorn.run("agent_client.main:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
