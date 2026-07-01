from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_store import save_config


def _refresh_dashboard_payload(root: Path) -> None:
    try:
        from src.dashboard_runner import write_dashboard_payload
    except Exception:
        return

    write_dashboard_payload(root / "dashboard_data.json", root / "runtime_payload.json")


class DashboardHandler(BaseHTTPRequestHandler):
    def __init__(self, *args: Any, directory: str | None = None, **kwargs: Any) -> None:
        self.directory = Path(directory or Path(__file__).resolve().parent.parent).resolve()
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/dashboard.html", "/index.html"}:
            self._serve_file(self.directory / "dashboard.html")
            return

        if path.startswith("/src/") or path.startswith("/tests/"):
            self._serve_file(self.directory / path.lstrip("/"))
            return

        if path.startswith("/dashboard_data.json"):
            self._serve_file(self.directory / "dashboard_data.json")
            return

        if path.startswith("/runtime_payload.json"):
            self._serve_file(self.directory / "runtime_payload.json")
            return

        if path.startswith("/learning_report.md"):
            self._serve_file(self.directory / "learning_report.md")
            return

        if path.startswith("/config.json"):
            self._serve_file(self.directory / "config.json")
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/save_config":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
            save_config(self.directory / "config.json", payload)
            _refresh_dashboard_payload(self.directory)
            self._send_json(200, {"status": "ok", "message": "Configured"})
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _serve_file(self, path: Path) -> None:
        if not path.exists():
            self._send_json(404, {"error": "file not found"})
            return

        mime = "text/html; charset=utf-8"
        if path.suffix == ".json":
            mime = "application/json; charset=utf-8"
        elif path.suffix == ".md":
            mime = "text/markdown; charset=utf-8"
        elif path.suffix == ".js":
            mime = "application/javascript; charset=utf-8"
        elif path.suffix == ".css":
            mime = "text/css; charset=utf-8"

        content = path.read_text(encoding="utf-8")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_dashboard_server(host: str = "127.0.0.1", port: int = 8000, directory: str | None = None) -> ThreadingHTTPServer:
    root = Path(directory or Path(__file__).resolve().parent.parent).resolve()
    os.chdir(root)
    server = ThreadingHTTPServer((host, port), lambda *args, **kwargs: DashboardHandler(*args, directory=str(root), **kwargs))
    print(f"Serving dashboard at http://{host}:{port}")
    server.serve_forever()
    return server


if __name__ == "__main__":
    run_dashboard_server()
