import json
import logging
import mimetypes
import re
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pychromecast
from pychromecast.controllers.youtube import YouTubeController

logging.basicConfig(stream=sys.stderr, level=logging.ERROR)


class MediaShare:
    def __init__(self, path, bind_address):
        self.path = Path(path).resolve(strict=True)
        if not self.path.is_file():
            raise ValueError("Choose a media file, not a folder.")
        self.token = secrets.token_urlsafe(32)
        self.mime = mimetypes.guess_type(str(self.path))[0] or "application/octet-stream"
        share = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                self.serve(False)

            def do_GET(self):
                self.serve(True)

            def serve(self, body):
                if self.path != "/" + share.token:
                    self.send_error(404)
                    return
                try:
                    with share.path.open("rb") as stream:
                        size = share.path.stat().st_size
                        start, end, code = 0, size - 1, 200
                        value = self.headers.get("Range")
                        if value:
                            match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
                            if not match or not any(match.groups()):
                                self.send_error(416)
                                return
                            left, right = match.groups()
                            if left:
                                start = int(left)
                                end = min(int(right), size - 1) if right else size - 1
                            else:
                                start = max(0, size - int(right))
                            if start >= size or end < start:
                                self.send_response(416)
                                self.send_header("Content-Range", f"bytes */{size}")
                                self.end_headers()
                                return
                            code = 206
                        length = max(0, end - start + 1)
                        self.send_response(code)
                        self.send_header("Content-Type", share.mime)
                        self.send_header("Content-Length", str(length))
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Cache-Control", "no-store")
                        if code == 206:
                            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                        self.end_headers()
                        if body:
                            stream.seek(start)
                            remaining = length
                            while remaining:
                                chunk = stream.read(min(262144, remaining))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                except OSError:
                    self.close_connection = True

            def setup(self):
                super().setup()
                self.connection.settimeout(15)

        self.server = ThreadingHTTPServer((bind_address, 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://{bind_address}:{self.server.server_port}/{self.token}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Service:
    def __init__(self):
        self.casts = {}
        self.browser = None
        self.current = None
        self.share = None

    def discover(self):
        if self.browser:
            self.browser.stop_discovery()
        casts, self.browser = pychromecast.get_chromecasts(timeout=6, tries=1, retry_wait=1)
        old = self.casts
        self.casts = {str(cast.uuid): cast for cast in casts}
        for identifier, cast in old.items():
            if cast is self.current:
                replacement = self.casts.pop(identifier, None)
                if replacement:
                    replacement.disconnect(timeout=1)
                self.casts[identifier] = cast
            else:
                cast.disconnect(timeout=1)
        return {"devices": sorted([
            {"id": identifier, "name": cast.name, "model": cast.model_name or "Google Cast"}
            for identifier, cast in self.casts.items()
        ], key=lambda item: item["name"].lower())}

    def select(self, identifier):
        cast = self.casts.get(identifier)
        if cast is None:
            raise ValueError("That device is unavailable. Refresh and select it again.")
        cast.wait(timeout=10)
        if self.current is not None and self.current is not cast and self.share:
            self.current.media_controller.stop()
            self.clear_share()
        self.current = cast
        return cast

    def clear_share(self):
        if self.share:
            self.share.close()
            self.share = None

    def play(self, request):
        cast = self.select(request.get("device"))
        path = request.get("path")
        next_share = None
        if path:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect((cast.cast_info.host, 8009))
                address = route.getsockname()[0]
            next_share = MediaShare(path, address)
            url, mime, title = next_share.url, next_share.mime, Path(path).name
        else:
            url = str(request.get("url", "")).strip()
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Enter an HTTP or HTTPS media link without embedded credentials.")
            host = parsed.hostname.lower()
            if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
                video = parsed.path.strip("/") if host == "youtu.be" else parse_qs(parsed.query).get("v", [""])[0]
                if not video and parsed.path.startswith(("/shorts/", "/live/")):
                    video = parsed.path.split("/")[2]
                if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
                    raise ValueError("Paste a link to a specific YouTube video.")
                controller = YouTubeController()
                cast.register_handler(controller)
                try:
                    controller.play_video(video)
                finally:
                    cast.unregister_handler(controller)
                self.clear_share()
                return {"message": "Sent to YouTube on your TV", "title": "YouTube", "status": self.status()}
            suffix = Path(parsed.path).suffix.lower()
            mime = {".m3u8": "application/x-mpegURL", ".mpd": "application/dash+xml"}.get(suffix) or mimetypes.guess_type(parsed.path)[0]
            if not mime or not mime.startswith(("video/", "audio/", "application/x-mpegURL", "application/dash+xml")):
                raise ValueError("Use a direct media link (MP4, MP3, HLS or DASH), or a YouTube video. Other website pages are not supported yet.")
            title = Path(parsed.path).name or "Online media"
        try:
            media = cast.media_controller
            media.app_must_match = True
            try:
                media.play_media(url, mime, title=title, stream_type="LIVE" if mime in ("application/x-mpegURL", "application/dash+xml") else "BUFFERED")
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if media.status.content_id == url and media.status.player_state in ("PLAYING", "PAUSED"):
                        break
                    if media.status.content_id == url and media.status.idle_reason == "ERROR":
                        raise RuntimeError("Your screen could not decode this media. Try an H.264/AAC MP4.")
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Your screen did not confirm playback. Check its supported formats and allow incoming connections for Hoist in your Mac’s firewall.")
            finally:
                media.app_must_match = False
        except Exception:
            if next_share:
                next_share.close()
            raise
        self.clear_share()
        self.share = next_share
        return {"message": "Playing on your screen.", "title": title, "status": self.status()}

    def status(self):
        if not self.current:
            return {"state": "IDLE", "title": "", "position": 0, "duration": 0, "volume": 0.5}
        status = self.current.media_controller.status
        return {
            "state": status.player_state or "IDLE", "title": status.title or "",
            "position": status.adjusted_current_time or 0, "duration": status.duration or 0,
            "volume": self.current.status.volume_level if self.current.status else 0.5,
            "device": str(self.current.uuid), "deviceName": self.current.name,
            "idleReason": status.idle_reason or "",
        }

    def handle(self, request):
        action = request.get("action")
        if action == "ping":
            return {"version": "0.1.0", "protocol": 1}
        if action == "discover":
            return self.discover()
        if action == "status":
            return self.status()
        if action == "play":
            return self.play(request)
        if not self.current:
            raise ValueError("Cast something first.")
        media = self.current.media_controller
        if action == "pause":
            media.pause()
        elif action == "resume":
            media.play()
        elif action == "stop":
            media.stop()
            self.clear_share()
        elif action == "seek":
            media.seek(max(0, float(request["position"])))
        elif action == "volume":
            self.current.set_volume(max(0, min(1, float(request["value"]))))
        else:
            raise ValueError("Unknown command.")
        return self.status()

    def close(self):
        self.clear_share()
        if self.browser:
            self.browser.stop_discovery()
        for cast in self.casts.values():
            try:
                cast.disconnect(timeout=1)
            except Exception:
                pass


def main():
    service = Service()
    try:
        for line in sys.stdin:
            identifier = None
            try:
                request = json.loads(line)
                identifier = request.get("id")
                result = service.handle(request)
                reply = {"id": identifier, "ok": True, "result": result}
            except Exception as error:
                reply = {"id": identifier, "ok": False, "error": str(error) or type(error).__name__}
            print(json.dumps(reply, allow_nan=False), flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    main()
