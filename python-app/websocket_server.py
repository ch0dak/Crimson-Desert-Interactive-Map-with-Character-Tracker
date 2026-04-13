"""
CD Map Tracker — WebSocket + HTTP Server
Broadcasts player position to connected clients and serves the web UI.
"""

import asyncio
import json
import logging
import os
import urllib.request
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

from config import WS_HOST, WS_PORT, VERSION

log = logging.getLogger("ws_server")

STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
}


class TrackerWebSocketServer:
    def __init__(self):
        self.clients = set()
        self.server = None
        self._message_handler = None  # callback for incoming messages

    def set_message_handler(self, handler):
        """Set callback for messages from clients: handler(msg_dict)"""
        self._message_handler = handler

    async def _proxy_tile(self, path):
        """Proxy a tile request to MapGenie with the correct Referer header.

        path format: /tiles/<realm>/<z>/<y>/<x>.jpg
        realm is 'pywel' or 'abyss'
        """
        TILE_BASES = {
            "pywel": "https://tiles.mapgenie.io/games/crimson-desert/pywel/default-v2",
            "abyss": "https://tiles.mapgenie.io/games/crimson-desert/oats/faction-v3",
        }
        parts = path.lstrip("/").split("/")  # ['tiles', realm, z, y, 'x.jpg']
        if len(parts) < 5:
            return Response(404, "Not Found", Headers())
        realm = parts[1]
        rest = "/".join(parts[2:])  # z/y/x.jpg
        base = TILE_BASES.get(realm)
        if not base:
            return Response(404, "Not Found", Headers())

        url = f"{base}/{rest}"

        def fetch():
            req = urllib.request.Request(url, headers={
                "Referer": "https://mapgenie.io/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read()

        try:
            data = await asyncio.to_thread(fetch)
            headers = Headers([
                ("Content-Type", "image/jpeg"),
                ("Content-Length", str(len(data))),
                ("Cache-Control", "public, max-age=86400"),
                ("Access-Control-Allow-Origin", "*"),
            ])
            return Response(200, "OK", headers, data)
        except Exception as e:
            log.debug(f"Tile proxy error {url}: {e}")
            return Response(404, "Not Found", Headers())

    async def _process_request(self, connection, request):
        """Handle HTTP requests for static files; return None to upgrade to WS."""
        # If this looks like a WebSocket upgrade, let it through
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None

        # Proxy tile requests to MapGenie
        path = request.path
        if path.startswith("/tiles/"):
            return await self._proxy_tile(path)

        # Serve static files
        path = request.path
        if path == "/" or path == "":
            path = "/index.html"

        # Security: prevent directory traversal
        safe_path = os.path.normpath(path.lstrip("/"))
        if safe_path.startswith("..") or os.path.isabs(safe_path):
            return Response(403, "Forbidden", Headers())

        file_path = os.path.join(STATIC_DIR, safe_path)
        if not os.path.isfile(file_path):
            return Response(404, "Not Found", Headers())

        ext = os.path.splitext(file_path)[1].lower()
        content_type = MIME_TYPES.get(ext, "application/octet-stream")

        try:
            mode = "r" if ext in (".html", ".json", ".js", ".css") else "rb"
            with open(file_path, mode, encoding="utf-8" if mode == "r" else None) as f:
                body = f.read()
            if isinstance(body, str):
                body = body.encode("utf-8")

            headers = Headers([
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                ("Access-Control-Allow-Origin", "*"),
                ("Cache-Control", "no-cache"),
            ])
            return Response(200, "OK", headers, body)
        except Exception as e:
            log.error(f"Error serving {file_path}: {e}")
            return Response(500, "Server Error", Headers())

    async def _handle_client(self, websocket):
        self.clients.add(websocket)
        addr = websocket.remote_address
        log.info(f"Client connected: {addr}")

        # Send hello
        await websocket.send(json.dumps({
            "type": "hello",
            "version": VERSION,
        }))

        try:
            async for message in websocket:
                try:
                    msg = json.loads(message)
                    log.debug(f"Received: {msg}")
                    if self._message_handler:
                        self._message_handler(msg)
                except json.JSONDecodeError:
                    log.warning(f"Invalid JSON from client: {message}")
        except Exception:
            pass
        finally:
            self.clients.discard(websocket)
            log.info(f"Client disconnected: {addr}")

    async def broadcast(self, msg_dict):
        """Send a message to all connected clients."""
        if not self.clients:
            return
        data = json.dumps(msg_dict)
        # Send to all, ignore individual failures
        disconnected = set()
        for ws in self.clients:
            try:
                await ws.send(data)
            except Exception:
                disconnected.add(ws)
        self.clients -= disconnected

    async def start(self):
        """Start the WebSocket + HTTP server."""
        self.server = await serve(
            self._handle_client,
            WS_HOST,
            WS_PORT,
            process_request=self._process_request,
        )
        log.info(f"Server listening on http://{WS_HOST}:{WS_PORT}")
        log.info(f"WebSocket available on ws://{WS_HOST}:{WS_PORT}")

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            log.info("Server stopped")

    @property
    def has_clients(self):
        return len(self.clients) > 0
