import json
import os
from pathlib import Path
import selectors
import struct
import subprocess
import sys
import tempfile
import time

root = Path(__file__).resolve().parents[1]
binary = str(root / "dist/Hoist.app/Contents/Resources/service/hoist-service")


def readable(pipe, timeout=15):
    selector = selectors.DefaultSelector()
    selector.register(pipe, selectors.EVENT_READ)
    events = selector.select(timeout)
    selector.close()
    assert events, "Process reply timed out"


with tempfile.TemporaryDirectory(prefix="hoist-", dir="/tmp") as runtime:
    environment = {**os.environ, "HOIST_RUNTIME_DIR": runtime}
    app = subprocess.Popen([binary, "--app-service"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    host = None
    try:
        app.stdin.write(b'{"id":"start","action":"ping"}\n')
        app.stdin.flush()
        readable(app.stdout)
        assert json.loads(app.stdout.readline())["ok"]
        assert (Path(runtime) / "cast.sock").stat().st_mode & 0o777 == 0o600
        host = subprocess.Popen([binary, "--native-host"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        def request(value):
            data = json.dumps(value).encode()
            host.stdin.write(struct.pack("=I", len(data)) + data)
            host.stdin.flush()
            readable(host.stdout)
            size = struct.unpack("=I", host.stdout.read(4))[0]
            return json.loads(host.stdout.read(size))
        reply = request({"id": "ping", "action": "ping"})
        assert reply["id"] == "ping" and reply["result"]["protocol"] == 2, reply
        assert request({"id": "status", "action": "status"})["result"]["state"] == "IDLE"
        assert not request({"id": "file", "action": "play", "path": "/etc/passwd"})["ok"]
        assert not request({"id": "unknown", "action": "readFile"})["ok"]
        assert not request({"id": "session", "action": "castMessage", "sessionId": "unapproved", "namespace": "urn:x-cast:com.google.cast.media", "data": {}})["ok"]
        host.stdin.close()
        assert host.wait(timeout=5) == 0
        app.stdin.close()
        assert app.wait(timeout=5) == 0
        assert not (Path(runtime) / "cast.sock").exists()
        print("PASS: packaged Firefox native framing, shared app IPC, request IDs, file-access rejection, session validation, socket permissions and cleanup")
    finally:
        for child in [host, app]:
            if child and child.poll() is None:
                child.kill()
                child.wait()
