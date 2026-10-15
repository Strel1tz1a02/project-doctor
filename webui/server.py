"""Stdlib demo console server: static single-page app + JSON API.

Run with ``uv run python webui/server.py`` (or plain ``python``) and open
``http://127.0.0.1:8080``. No web framework, no new dependencies.

Routes
    GET  /                              -> static/index.html
    GET  /static/<file>                 -> static asset
    GET  /api/cases                     -> 45-case metadata matrix
    GET  /api/env                       -> capability detection
    POST /api/run {mode, only_bundled, case_ids?} -> {run_id}
    GET  /api/runs                      -> run summaries
    GET  /api/runs/<id>                 -> run status + progress + report
    GET  /api/runs/<id>/case/<case_id>  -> one case's scored result
"""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from runners import RunManager, detect_env, list_cases, load_config

_STATIC = Path(__file__).resolve().parent / "static"

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


class Handler(BaseHTTPRequestHandler):
    manager: RunManager
    config: dict[str, Any]

    # -- helpers --------------------------------------------------------------
    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: str, status: int = HTTPStatus.OK) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._text("not found", HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", _MIME.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # -- HTTP verbs -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/index.html":
            self._file(_STATIC / "index.html")
        elif path.startswith("/static/"):
            name = path[len("/static/") :]
            target = (_STATIC / name).resolve()
            if _STATIC not in target.parents:
                self._text("forbidden", HTTPStatus.FORBIDDEN)
                return
            self._file(target)
        elif path == "/api/cases":
            self._json(list_cases(Path(self.config["cases_root"])))
        elif path == "/api/env":
            self._json(detect_env(self.config))
        elif path == "/api/runs":
            self._json(self.manager.list_runs())
        elif path.startswith("/api/runs/"):
            self._route_run_get(path[len("/api/runs/") :])
        else:
            self._text("not found", HTTPStatus.NOT_FOUND)

    def _route_run_get(self, rest: str) -> None:
        parts = [p for p in rest.split("/") if p]
        if not parts:
            self._json(self.manager.list_runs())
            return
        run_id = parts[0]
        if len(parts) == 1:
            snapshot = self.manager.get(run_id)
            if snapshot is None:
                self._text("no such run", HTTPStatus.NOT_FOUND)
            else:
                self._json(snapshot)
        elif len(parts) == 3 and parts[1] == "case":
            detail = self.manager.case_detail(run_id, parts[2])
            if detail is None:
                self._text("no such case result", HTTPStatus.NOT_FOUND)
            else:
                self._json(detail)
        else:
            self._text("not found", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/run":
            self._text("not found", HTTPStatus.NOT_FOUND)
            return
        body = self._read_json_body()
        mode = body.get("mode", "offline")
        if mode not in ("offline", "real"):
            self._json({"error": f"未知模式：{mode}"}, HTTPStatus.BAD_REQUEST)
            return
        only_bundled = bool(body.get("only_bundled", False))
        case_ids = body.get("case_ids")
        run_id = self.manager.start(mode, only_bundled, case_ids)
        self._json({"run_id": run_id})

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        print(f"[webui] {self.address_string()} {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Project Doctor 诊断评测台")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认读 config.json）")
    parser.add_argument("--host", default=None, help="监听地址（默认读 config.json）")
    parser.add_argument("--config", default=None, help="config.json 路径（默认 webui/config.json）")
    args = parser.parse_args()

    config = load_config(Path(args.config) if args.config else None)
    host = args.host or config.get("host") or "127.0.0.1"
    port = args.port or int(config.get("port") or 8080)
    cases_root = Path(config.get("cases_root") or "datasets")
    if not cases_root.is_absolute():
        cases_root = Path(__file__).resolve().parents[1] / cases_root
    config["cases_root"] = str(cases_root)

    Handler.manager = RunManager(config)
    Handler.config = config
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[webui] Project Doctor 诊断评测台 -> http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[webui] 停止")


if __name__ == "__main__":
    main()
