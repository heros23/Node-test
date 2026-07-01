import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib import request

from src.dashboard_server import DashboardHandler


def test_dashboard_server_script_serves_page() -> None:
    root = Path(__file__).resolve().parent.parent
    process = subprocess.Popen(
        [sys.executable, "src/dashboard_server.py"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        deadline = time.time() + 10
        page = None
        while time.time() < deadline:
            try:
                with request.urlopen("http://127.0.0.1:8000/dashboard.html", timeout=1) as response:
                    page = response.read().decode("utf-8")
                    break
            except Exception:
                time.sleep(0.2)

        assert page is not None
        assert "자동매매 대시보드" in page
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_dashboard_server_serves_page_and_saves_config(tmp_path: Path) -> None:
    from http.server import ThreadingHTTPServer

    root = Path(__file__).resolve().parent.parent
    server = ThreadingHTTPServer(("127.0.0.1", 0), lambda *args, **kwargs: DashboardHandler(*args, directory=str(root), **kwargs))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with request.urlopen(f"http://127.0.0.1:{server.server_port}/dashboard.html") as response:
            body = response.read().decode("utf-8")
            assert "자동매매 대시보드" in body

        payload = json.dumps({"base_url": "https://example.test", "api_key": "k", "api_secret": "s"}).encode("utf-8")
        req = request.Request(
            f"http://127.0.0.1:{server.server_port}/save_config",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req) as response:
            assert response.status == 200

        saved = (root / "config.json").read_text(encoding="utf-8")
        assert "https://example.test" in saved
    finally:
        server.shutdown()
        server.server_close()
