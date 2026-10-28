"""Loopback-only, live view and failed-test repair of workflow files."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading

from .execution import rerun_failed
import webbrowser

import yaml

from .view import render_view


def make_server(flow_dir, port=0):
    flow = Path(flow_dir).resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/rerun':
                self.send_error(404)
                return
            # Reject cross-origin browser requests before starting code execution.
            if self.headers.get('Origin') != 'http://' + self.headers.get('Host', ''):
                self.send_error(403)
                return
            if self.headers.get('X-ARC-Rerun') != '1':
                self.send_error(403)
                return
            if server.repair_worker and server.repair_worker.is_alive():
                self.send_error(409, 're-run already in progress')
                return
            def repair():
                try:
                    rerun_failed(flow)
                except (OSError, ValueError):
                    pass  # Persisted in rerun.json for the live view.
            server.repair_worker = threading.Thread(target=repair, daemon=True)
            server.repair_worker.start()
            self.send_response(202)
            self.end_headers()

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

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.repair_worker = None
    return server


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
