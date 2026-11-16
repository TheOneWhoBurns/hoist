import fcntl
import json
import os
from pathlib import Path
import socket
import struct
import sys
import threading

EXTENSION_ID = "hoist@theonewhoburns.github.io"
HOST_NAME = "io.github.theonewhoburns.hoist"
MAX_MESSAGE = 256 * 1024


def bridge_directory():
    directory = Path(os.environ["HOIST_RUNTIME_DIR"]) if "HOIST_RUNTIME_DIR" in os.environ else Path.home() / "Library/Application Support/Hoist"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    return directory


def socket_path():
    return str(bridge_directory() / "cast.sock")


class NativeServer:
    def __init__(self, dispatch):
        self.dispatch = dispatch
        self.lock = (bridge_directory() / "cast.lock").open("w")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.path = socket_path()
        Path(self.path).unlink(missing_ok=True)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(self.path)
        os.chmod(self.path, 0o600)
        self.socket.listen(8)
        self.closed = False
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while not self.closed:
            try:
                connection, _ = self.socket.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(connection,), daemon=True).start()

    def handle(self, connection):
        with connection:
            connection.settimeout(40)
            stream = connection.makefile("rb")
            try:
                line = stream.readline(MAX_MESSAGE + 1)
                if len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                    raise ValueError("Message too large or incomplete.")
                request = json.loads(line)
                allowed = {"ping", "discover", "status", "play", "pause", "resume", "stop", "seek", "volume", "mute", "launch", "castMessage", "castEvents", "loadMedia", "endSession"}
                if not isinstance(request, dict) or request.get("action") not in allowed or "path" in request:
                    raise ValueError("This command is not available to the browser companion.")
                reply = self.dispatch(request)
            except Exception as error:
                reply = {"ok": False, "error": str(error)}
            try:
                connection.sendall(json.dumps(reply, allow_nan=False).encode() + b"\n")
            except OSError:
                pass

    def close(self):
        self.closed = True
        self.socket.close()
        Path(self.path).unlink(missing_ok=True)
        self.lock.close()


def native_main():
    while True:
        request = {}
        header = sys.stdin.buffer.read(4)
        if not header:
            return
        if len(header) != 4:
            return
        length = struct.unpack("=I", header)[0]
        if length > MAX_MESSAGE:
            return
        body = sys.stdin.buffer.read(length)
        if len(body) != length:
            return
        try:
            request = json.loads(body)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(40)
                connection.connect(socket_path())
                connection.sendall(json.dumps(request).encode() + b"\n")
                response = connection.makefile("rb").readline(MAX_MESSAGE + 1)
                if not response.endswith(b"\n") or len(response) > MAX_MESSAGE:
                    raise ValueError("Invalid response from Hoist.")
                reply = json.loads(response)
        except OSError:
            reply = {"ok": False, "error": "Open Hoist 0.2.0 or newer from Applications, then try again."}
        except Exception as error:
            reply = {"ok": False, "error": str(error)}
        if isinstance(request, dict):
            reply["id"] = request.get("id")
        encoded = json.dumps(reply, allow_nan=False).encode()
        sys.stdout.buffer.write(struct.pack("=I", len(encoded)) + encoded)
        sys.stdout.buffer.flush()
