(() => {
  if (globalThis.__hoistContentInstalled) return;
  globalThis.__hoistContentInstalled = true;
  window.addEventListener("message", async event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.channel !== "hoist:request") return;
    const {id, request} = event.data;
    if (typeof id !== "string" || !request || JSON.stringify(request).length > 128000) return;
    try {
      const reply = await browser.runtime.sendMessage({...request, kind: "page"});
      window.postMessage({channel: "hoist:reply", id, ...reply}, location.origin);
    } catch (error) {
      window.postMessage({channel: "hoist:reply", id, ok: false, error: error.message}, location.origin);
    }
  });
  browser.runtime.onMessage.addListener(message => {
    if (message.kind === "update" || message.kind === "ended") window.postMessage({channel: "hoist:event", ...message}, location.origin);
  });
})();
