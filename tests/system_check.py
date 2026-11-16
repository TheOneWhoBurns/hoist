import hashlib
import http.client
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[1]
service = sys.argv[1:] or [sys.executable, str(root / "service/hoist_service.py")]


def read_line(process):
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    ready = selector.select(15)
    selector.close()
    if not ready:
        raise RuntimeError("Child process failed to reply within 15 seconds")
    return process.stdout.readline()


process = subprocess.Popen(service, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=root)
try:
    for message, expected in [({"id": 1, "action": "ping"}, True), ({"id": 2, "action": "status"}, True), ({"id": 3, "action": "pause"}, False)]:
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
        reply = json.loads(read_line(process))
        assert reply["id"] == message["id"] and reply["ok"] is expected, reply
    process.stdin.write("invalid json\n")
    process.stdin.flush()
    assert json.loads(read_line(process))["ok"] is False
    process.stdin.close()
    assert process.wait(timeout=10) == 0
finally:
    if process.poll() is None:
        process.kill()
        process.wait()
print("PASS: standalone service protocol, errors, clean shutdown")

with tempfile.TemporaryDirectory() as directory:
    media = Path(directory) / "fixture.mp4"
    payload = bytes(range(256)) * 4096
    media.write_bytes(payload)
    server = subprocess.Popen([
        sys.executable, "-c",
        "import sys; from service.hoist_service import MediaShare; s=MediaShare(sys.argv[1], '127.0.0.1'); print(s.url, flush=True); sys.stdin.readline(); s.close()",
        str(media),
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=root)
    try:
        url = urlsplit(read_line(server).strip())
        def fetch(path, method="GET", headers=None):
            connection = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            body = response.read()
            values = (response.status, dict(response.getheaders()), body)
            connection.close()
            return values
        status, headers, body = fetch(url.path)
        assert status == 200 and hashlib.sha256(body).digest() == hashlib.sha256(payload).digest()
        assert headers["Content-Type"] == "video/mp4"
        status, headers, body = fetch(url.path, "HEAD")
        assert status == 200 and not body and int(headers["Content-Length"]) == len(payload)
        status, headers, body = fetch(url.path, headers={"Range": "bytes=100-199"})
        assert status == 206 and body == payload[100:200]
        assert headers["Content-Range"] == f"bytes 100-199/{len(payload)}"
        status, _, body = fetch(url.path, headers={"Range": "bytes=-128"})
        assert status == 206 and body == payload[-128:]
        status, _, body = fetch(url.path, headers={"Range": "bytes=1048500-"})
        assert status == 206 and body == payload[1048500:]
        for value in ["bytes=999999999-", "bytes=200-100", "bytes=0-10,20-30", "bytes=-0"]:
            assert fetch(url.path, headers={"Range": value})[0] == 416
        for path in ["/", "/wrong-token", "/../fixture.mp4", url.path + "/../fixture.mp4"]:
            assert fetch(path)[0] == 404
        server.stdin.write("stop\n")
        server.stdin.flush()
        assert server.wait(timeout=5) == 0
        print("PASS: file transfer, seeking ranges, HEAD, token isolation, invalid ranges, shutdown")
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()
