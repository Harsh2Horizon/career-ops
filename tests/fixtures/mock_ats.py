"""Local no-network mock application server; never forwards data to real employers."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML = Path(__file__).with_name("mock_application.html").read_bytes()


@contextmanager
def serve():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(HTML)))
            self.end_headers()
            self.wfile.write(HTML)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/apply"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    with serve() as url:
        print(url, flush=True)
        threading.Event().wait()
