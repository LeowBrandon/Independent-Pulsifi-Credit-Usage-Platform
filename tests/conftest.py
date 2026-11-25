"""Pytest fixtures providing isolated SQLite DB and live FastAPI HTTP test client (zero httpx dep)."""
from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import uvicorn

# Ensure backend/ is importable as `app.*`
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import DatabaseManager
from app.main import create_app
from app.seed import seed_database


class SimpleHTTPClient:
    """Lightweight stdlib HTTP client for end-to-end FastAPI testing."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        raw_body: bytes | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        hdrs = dict(headers or {})
        body: bytes | None = raw_body
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()

        ct = resp_headers.get("content-type", "")
        if "application/json" in ct:
            parsed = json.loads(data.decode("utf-8"))
        else:
            parsed = data.decode("utf-8", errors="replace")
        return resp.status, resp_headers, parsed

    def post_multipart(
        self,
        path: str,
        *,
        fields: dict[str, str] | None = None,
        file_field: str = "file",
        filename: str = "upload.csv",
        file_content: str = "",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        boundary = "----PulsifiTestBoundary7MA4YWxkTrZu0gW"
        parts: list[bytes] = []
        for k, v in (fields or {}).items():
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
                f"{v}\r\n".encode("utf-8")
            )
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: text/csv\r\n\r\n"
            f"{file_content}\r\n"
            f"--{boundary}--\r\n".encode("utf-8")
        )
        raw = b"".join(parts)
        hdrs = dict(headers or {})
        hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        return self.request("POST", path, raw_body=raw, headers=hdrs)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def seeded_db(tmp_path: Path) -> DatabaseManager:
    db = DatabaseManager(tmp_path / "test_pulsifi.db")
    db.init_schema()
    with db.session() as conn:
        seed_database(conn, write_sample_csv=False)
    return db


@pytest.fixture()
def api_client(tmp_path: Path) -> SimpleHTTPClient:
    db_file = tmp_path / "api_test.db"
    app = create_app(db_path=db_file, seed=True)
    port = _find_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    client = SimpleHTTPClient("127.0.0.1", port)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            status, _, _ = client.request("GET", "/api/health")
            if status == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("Test server failed to start in time")

    yield client
    server.should_exit = True
    thread.join(timeout=3.0)
