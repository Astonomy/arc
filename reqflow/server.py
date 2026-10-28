"""Loopback-only, read-only live view of workflow files."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import webbrowser

import yaml

from .view import render_view


def make_server(flow_dir, port=0):
    flow = Path(flow_dir).resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in {"/", "/snapshot"}:
                self.send_error(404)
                return
            try:
                with tempfile.TemporaryDirectory() as directory:
                    content = render_view(flow, Path(directory) / "view.html").read_bytes()
            except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
                self.send_error(503, str(exc))
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(flow_dir, port=0, open_browser=True):
    with make_server(flow_dir, port) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(url, flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
