"""HTTP transport for controlling a native editor window over localhost."""
from http.server import BaseHTTPRequestHandler
import json
from socketserver import TCPServer
from urllib.parse import urlsplit


class LocalServer(TCPServer):
    allow_reuse_address = True


class PreviewHandler(BaseHTTPRequestHandler):
    viewer = None

    def respond(self, value, status=200, *, content_type=None):
        if isinstance(value, str):
            body, media = value.encode(), 'image/svg+xml'
        elif isinstance(value, bytes):
            body, media = value, 'image/png'
        else:
            body, media = json.dumps(value).encode(), 'application/json'
        self.send_response(status)
        self.send_header('Content-Type', content_type or media)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 1024 * 1024:
            raise ValueError('invalid request size')
        return json.loads(self.rfile.read(length))

    def get_resource(self, url):
        self.respond({'error': 'unknown endpoint'}, 404)

    def post_resource(self):
        self.respond({'error': 'unknown endpoint'}, 404)

    def do_GET(self):
        try:
            url = urlsplit(self.path)
            if self.viewer is not None and url.path in ('/view', '/view.png'):
                action = 'snapshot' if url.path.endswith('.png') else 'state'
                self.respond(self.viewer.request(action))
            else:
                self.get_resource(url)
        except TimeoutError as error:
            self.respond({'error': str(error)}, 503)
        except (ValueError, KeyError, OSError) as error:
            self.respond({'error': str(error)}, 400)

    def do_POST(self):
        try:
            if self.path == '/view' and self.viewer is not None:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('view updates require application/json')
                self.respond(self.viewer.request('update', self.read_json()))
            else:
                self.post_resource()
        except TimeoutError as error:
            self.respond({'error': str(error)}, 503)
        except (AttributeError, ValueError, KeyError, TypeError, IndexError, OSError) as error:
            status = 409 if str(error).startswith('map revision changed') else 400
            self.respond({'error': str(error)}, status)


def viewer_server(port, window, handler=PreviewHandler):
    class Handler(handler):
        viewer = window

    return LocalServer(('127.0.0.1', port), Handler)
