import json
import logging
import mimetypes
import re
import secrets
import socket
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pychromecast
from pychromecast.controllers.youtube import YouTubeController
from pychromecast.controllers import BaseController
try:
    from .native_bridge import NativeServer, native_main
except ImportError:
    from native_bridge import NativeServer, native_main

logging.basicConfig(stream=sys.stderr, level=logging.ERROR)


class NamespaceRelay(BaseController):
    def __init__(self, namespace, callback):
        super().__init__(namespace)
        self.callback = callback

    def receive_message(self, message, data):
        self.callback(self.namespace, data)
        return True


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
        self.relays = []
        self.relay_cast = None
        self.events = deque(maxlen=100)
        self.event_sequence = 0
        self.event_lock = threading.Lock()

    def record_event(self, namespace, data):
        with self.event_lock:
            self.event_sequence += 1
            self.events.append({"sequence": self.event_sequence, "namespace": namespace, "data": data})

    def session(self):
        if not self.current or not self.current.status:
            return None
        status = self.current.status
        return {"sessionId": status.session_id, "appId": status.app_id, "displayName": status.display_name,
                "receiver": {"label": str(self.current.uuid), "friendlyName": self.current.name,
                             "volume": {"level": status.volume_level, "muted": status.volume_muted}},
                "namespaces": [{"name": name} for name in status.namespaces], "status": "connected"}

    def browser_action(self, request):
        action = request["action"]
        if action == "launch":
            app_id = request.get("appId", "CC1AD845")
            if not isinstance(app_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", app_id):
                raise ValueError("Invalid Cast application ID.")
            cast = self.select(request.get("device"))
            for relay in self.relays:
                self.relay_cast.unregister_handler(relay)
            self.relays.clear()
            self.relay_cast = cast
            with self.event_lock:
                self.events.clear()
            cast.socket_client.receiver_controller.launch_app(app_id)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if cast.status and cast.status.app_id == app_id and cast.status.session_id:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("The requested receiver app did not start on your screen.")
            for namespace in cast.status.namespaces:
                if namespace != "urn:x-cast:com.google.cast.media":
                    relay = NamespaceRelay(namespace, self.record_event)
                    cast.register_handler(relay)
                    self.relays.append(relay)
            self.clear_share()
            return {"session": self.session(), "status": self.status()}
        if not self.current or request.get("sessionId") != self.current.status.session_id:
            raise ValueError("The Cast session has ended or changed. Connect again.")
        if action == "castMessage":
            namespace = request.get("namespace", "")
            if namespace not in self.current.status.namespaces or not namespace.startswith("urn:x-cast:"):
                raise ValueError("This receiver does not support that message namespace.")
            data = request.get("data")
            if not isinstance(data, dict):
                raise ValueError("Cast messages must be JSON objects.")
            self.current.socket_client.send_app_message(namespace, data, no_add_request_id=True)
            return {}
        if action == "castEvents":
            with self.event_lock:
                events = [event for event in self.events if event["sequence"] > request.get("after", 0)]
            return {"events": events, "session": self.session(), "status": self.status()}
        if action == "endSession":
            self.current.quit_app()
            self.clear_share()
            return {}
        if action == "loadMedia":
            media = request.get("media", {})
            url = media.get("contentId", "")
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("The media must have a direct HTTP(S) URL. Browser blob URLs cannot be cast.")
            payload = {"type": "LOAD", "media": media, "autoplay": bool(request.get("autoplay", True)), "currentTime": max(0, float(request.get("currentTime") or 0))}
            self.current.socket_client.send_app_message("urn:x-cast:com.google.cast.media", payload, inc_session_id=True)
            return {"status": self.status()}
        raise ValueError("Unknown browser command.")

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
            "session": self.session(), "contentId": status.content_id or "", "contentType": status.content_type or "",
            "mediaSessionId": status.media_session_id,
        }

    def handle(self, request):
        action = request.get("action")
        if action == "ping":
            return {"version": "0.2.1", "protocol": 2}
        if action in ("launch", "castMessage", "castEvents", "loadMedia", "endSession"):
            return self.browser_action(request)
        if action == "discover":
            return self.discover()
        if action == "status":
            return self.status()
        if action == "play":
            return self.play(request)
        if not self.current:
            raise ValueError("Cast something first.")
        if request.get("sessionId") and request["sessionId"] != self.current.status.session_id:
            raise ValueError("The Cast session changed. Connect again.")
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
        elif action == "mute":
            self.current.set_volume_muted(bool(request.get("value")))
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
    if "--native-host" in sys.argv:
        native_main()
        return
    service = Service()
    lock = threading.Lock()
    def dispatch(request):
        with lock:
            try:
                return {"id": request.get("id"), "ok": True, "result": service.handle(request)}
            except Exception as error:
                return {"id": request.get("id"), "ok": False, "error": str(error) or type(error).__name__}
    server = NativeServer(dispatch) if "--app-service" in sys.argv else None
    try:
        for line in sys.stdin:
            identifier = None
            try:
                request = json.loads(line)
                identifier = request.get("id")
                reply = dispatch(request)
            except Exception as error:
                reply = {"id": identifier, "ok": False, "error": str(error) or type(error).__name__}
            print(json.dumps(reply, allow_nan=False), flush=True)
    finally:
        if server:
            server.close()
        service.close()


if __name__ == "__main__":
    main()
