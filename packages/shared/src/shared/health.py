"""Standardized health check utilities."""

import http.server
import json
import logging
import socketserver
import threading

logger = logging.getLogger(__name__)


class HealthHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler exposing /health."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: ARG002
        pass


def start_health_server(port: int = 8000) -> socketserver.TCPServer:
    """Start a simple health check server in a background thread."""
    server = socketserver.TCPServer(("", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health server started on port %d", port)
    return server
