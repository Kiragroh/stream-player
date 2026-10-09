"""Media-only HTTP endpoint for Google Cast. No website or control API."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import secrets
import threading
from urllib.parse import urlsplit
from .casting import lan_address


class MediaServer:
    def __init__(self, library, host='0.0.0.0', port=0):
        self.library = library
        self.identity = None
        self.token = secrets.token_urlsafe(32)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def end_headers(self):
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Headers', 'Range')
                self.send_header('Access-Control-Expose-Headers', 'Content-Range,Accept-Ranges,Content-Length')
                self.send_header('Cache-Control', 'no-store')
                super().end_headers()

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header('Access-Control-Allow-Methods', 'GET,HEAD,OPTIONS')
                self.end_headers()

            def do_GET(self):
                self.serve_file(False)

            def do_HEAD(self):
                self.serve_file(True)

            def serve_file(self, head):
                match = re.fullmatch(r'/video/([^/]+)/([a-f0-9]+)\.mp4', urlsplit(self.path).path)
                if not match or not secrets.compare_digest(match[1], owner.token) or match[2] != owner.identity:
                    self.send_error(404)
                    return
                try:
                    item = owner.library.ready(match[2])
                    source = item['output'].open('rb')
                except (ValueError, OSError):
                    self.send_error(404)
                    return
                with source:
                    source.seek(0, 2)
                    size = source.tell()
                    start, end = 0, size - 1
                    byte_range = self.headers.get('Range')
                    if byte_range:
                        bounds = re.fullmatch(r'bytes=(\d*)-(\d*)', byte_range)
                        try:
                            if not bounds or not any(bounds.groups()):
                                raise ValueError()
                            if not bounds[1]:
                                suffix = int(bounds[2])
                                if suffix <= 0:
                                    raise ValueError()
                                start = max(0, size - suffix)
                            else:
                                start = int(bounds[1])
                                end = min(int(bounds[2]), end) if bounds[2] else end
                            if start > end or start >= size:
                                raise ValueError()
                        except ValueError:
                            self.send_response(416)
                            self.send_header('Content-Range', f'bytes */{size}')
                            self.send_header('Content-Length', '0')
                            self.end_headers()
                            return
                    self.send_response(206 if byte_range else 200)
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('Content-Length', str(end - start + 1))
                    self.send_header('Accept-Ranges', 'bytes')
                    if byte_range:
                        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    if head:
                        return
                    source.seek(start)
                    remaining = end - start + 1
                    try:
                        while remaining:
                            chunk = source.read(min(256 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    except (ConnectionError, OSError):
                        pass

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def share(self, identity, receiver):
        self.library.ready(identity)
        self.identity = identity
        return f'http://{lan_address(receiver)}:{self.server.server_port}/video/{self.token}/{identity}.mp4'

    def revoke(self):
        self.identity = None
        self.token = secrets.token_urlsafe(32)

    def close(self):
        self.revoke()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
