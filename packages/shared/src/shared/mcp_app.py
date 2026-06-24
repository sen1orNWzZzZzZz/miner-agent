"""Helper to expose a FastMCP server over SSE via Starlette."""

from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


class _AlreadySentResponse(Response):
    """Placeholder response for endpoints that already sent headers."""

    async def __call__(self, scope, receive, send):  # noqa: ARG002
        return None


def create_mcp_starlette_app(
    mcp: FastMCP,
    health_response: dict | None = None,
    extra_routes: list[Route] | None = None,
) -> Starlette:
    """Wrap a FastMCP instance into a Starlette app with SSE + health endpoints.

    ``extra_routes`` lets a server expose additional plain HTTP endpoints (e.g. a
    runtime config API) alongside the MCP SSE transport.
    """
    server = mcp._mcp_server
    sse = SseServerTransport("/messages")

    async def sse_endpoint(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        # SSE connection is already handled above; return a no-op placeholder.
        return _AlreadySentResponse(status_code=200)

    async def messages_endpoint(request):
        # handle_post_message writes the 202 response directly; we return a
        # no-op placeholder so Starlette's request/response cycle completes.
        await sse.handle_post_message(
            request.scope, request.receive, request._send
        )
        return _AlreadySentResponse(status_code=202)

    async def health(request):  # noqa: ARG001
        return JSONResponse(health_response or {"status": "healthy"})

    routes = [
        Route("/sse", sse_endpoint),
        Route("/messages", messages_endpoint, methods=["POST"]),
        Route("/health", health),
    ]
    if extra_routes:
        routes.extend(extra_routes)

    return Starlette(debug=False, routes=routes)
