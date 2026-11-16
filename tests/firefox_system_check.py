import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

root = Path(__file__).resolve().parents[1]
result = {}
complete = threading.Event()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        result.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()
        complete.set()

    def do_GET(self):
        source = """<!doctype html><html><head><title>Hoist system check</title></head><body><h1>Hoist Firefox system check</h1><script>
        const report = value => fetch('/report', {method:'POST',body:JSON.stringify(value)});
        const deadline = setTimeout(() => report({ok:false,error:'Sender API did not become available'}), 20000);
        const begin = () => {
          if (!window.chrome?.cast?.isAvailable) return setTimeout(begin,100);
          clearTimeout(deadline);
          const api = window.chrome.cast;
          const config = new api.ApiConfig(new api.SessionRequest('CC1AD845'),()=>{}, availability => {
            window.hoistAvailability = availability;
          });
          api.initialize(config, () => {
            api.requestSession(() => report({ok:false,error:'Unexpected session without approval'}), error => {
              report({ok:true,api:api.isAvailable,availability:window.hoistAvailability,cancelError:error.description,
                framework:!!window.cast.framework.CastContext.getInstance(),launcher:!!customElements.get('google-cast-launcher')});
            });
          }, error => report({ok:false,error:error.description}));
        }; begin();
        </script></body></html>""".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(source)))
        self.end_headers()
        self.wfile.write(source)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}"
native_directory = Path.home() / "Library/Application Support/Mozilla/NativeMessagingHosts"
native_directory.mkdir(parents=True, exist_ok=True)
manifest_path = native_directory / "io.github.theonewhoburns.hoist.json"
previous_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
with tempfile.TemporaryDirectory(prefix="hoist-firefox-", dir="/tmp") as temporary:
    temporary = Path(temporary)
    addon = temporary / "extension"
    shutil.copytree(root / "extension", addon)
    manifest = json.loads((addon / "manifest.json").read_text())
    manifest["host_permissions"] = ["http://127.0.0.1/*"]
    (addon / "manifest.json").write_text(json.dumps(manifest))
    with (addon / "background.js").open("a") as file:
        file.write("\n" + """
        (async () => {
          await native({action:'ping'});
          await registerSites();
          await browser.tabs.create({url:BASE + '/check'});
          const cancelTimer = setInterval(async () => {
            for (const item of approvals.values()) {
              if (item.windowId !== null) {
                clearInterval(cancelTimer);
                await browser.windows.remove(item.windowId);
                return;
              }
            }
          }, 200);
          setTimeout(() => clearInterval(cancelTimer), 30000);
        })().catch(error => fetch(BASE + '/report',{method:'POST',body:JSON.stringify({ok:false,error:error.message})}));
        """.replace("BASE", json.dumps(base)))
    binary = root / "dist/Hoist.app/Contents/Resources/service/hoist-service"
    native_manifest = {"name": "io.github.theonewhoburns.hoist", "description": "Hoist system check", "path": str(root / "dist/Hoist.app/Contents/Resources/hoist-native"), "type": "stdio", "allowed_extensions": ["hoist@theonewhoburns.github.io"]}
    manifest_path.write_text(json.dumps(native_manifest))
    environment = {**os.environ, "HOIST_RUNTIME_DIR": str(temporary / "runtime")}
    app = subprocess.Popen([str(binary), "--app-service"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    firefox = None
    try:
        app.stdin.write(b'{"action":"ping"}\n')
        app.stdin.flush()
        assert json.loads(app.stdout.readline())["ok"]
        log_path = root / "build/firefox-system-check.log"
        with log_path.open("w") as log:
            firefox = subprocess.Popen(["npx", "--yes", "web-ext", "run", "--source-dir", str(addon), "--firefox", "/Applications/Firefox.app/Contents/MacOS/firefox", "--no-config-discovery", "--no-reload", "--no-input", "--arg=-headless"], stdout=log, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
            if not complete.wait(55):
                raise RuntimeError("Firefox check timed out; inspect build/firefox-system-check.log")
        assert result.get("ok"), result
        assert result.get("api") and result.get("framework") and result.get("launcher"), result
        assert "cancel" in result.get("cancelError", "").lower(), result
        print("PASS: real Firefox temporary extension, MAIN-world API, isolated bridge, native messaging, device discovery, extension-owned picker and cancellation")
        print(json.dumps(result))
    finally:
        if firefox and firefox.poll() is None:
            os.killpg(firefox.pid, signal.SIGTERM)
            try:
                firefox.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(firefox.pid, signal.SIGKILL)
                firefox.wait()
        app.stdin.close()
        try:
            app.wait(timeout=5)
        except subprocess.TimeoutExpired:
            app.kill()
            app.wait()
        if previous_manifest is None:
            manifest_path.unlink(missing_ok=True)
        else:
            manifest_path.write_bytes(previous_manifest)
        server.shutdown()
