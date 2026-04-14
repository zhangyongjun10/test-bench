from __future__ import annotations

import http.server
import urllib.error
import urllib.request
from pathlib import Path


DIST_DIR = Path(__file__).resolve().parent / "dist"
BACKEND_BASE_URL = "http://127.0.0.1:8000"


class PreviewHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._proxy("GET")
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._proxy("POST")
            return
        self.send_error(405)

    def do_PUT(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._proxy("PUT")
            return
        self.send_error(405)

    def do_DELETE(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._proxy("DELETE")
            return
        self.send_error(405)

    def _proxy(self, method: str) -> None:
        body = None
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length:
            body = self.rfile.read(content_length)

        request = urllib.request.Request(f"{BACKEND_BASE_URL}{self.path}", data=body, method=method)
        for key, value in self.headers.items():
            if key.lower() not in {"host", "content-length", "connection"}:
                request.add_header(key, value)

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in {"transfer-encoding", "connection", "content-encoding"}:
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(response.read())
        except urllib.error.HTTPError as exc:
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() not in {"transfer-encoding", "connection", "content-encoding"}:
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(exc.read())
        except Exception as exc:  # pragma: no cover - local preview helper
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8", errors="replace"))


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 3000), PreviewHandler)
    print("Preview server listening on http://127.0.0.1:3000")
    server.serve_forever()
