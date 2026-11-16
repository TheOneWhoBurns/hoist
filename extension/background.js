const HOST = "io.github.theonewhoburns.hoist";
let port;
const replies = new Map();
const approvals = new Map();
const sessions = new Map();
const pollBusy = new Set();

function native(command) {
  if (!port) {
    port = browser.runtime.connectNative(HOST);
    port.onMessage.addListener(reply => {
      const pending = replies.get(reply.id);
      if (!pending) return;
      replies.delete(reply.id);
      clearTimeout(pending.timer);
      reply.ok ? pending.resolve(reply.result) : pending.reject(new Error(reply.error || "Hoist could not complete that request."));
    });
    port.onDisconnect.addListener(() => {
      const reason = port?.error?.message || "Open Hoist 0.2.0 or newer, then try again.";
      port = null;
      for (const pending of replies.values()) { clearTimeout(pending.timer); pending.reject(new Error(reason)); }
      replies.clear();
    });
  }
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timer = setTimeout(() => { replies.delete(id); reject(new Error("Hoist took too long to respond.")); }, 45000);
    replies.set(id, {resolve, reject, timer});
    port.postMessage({...command, id});
  });
}

let registration = Promise.resolve();
function registerSites() {
  registration = registration.catch(() => {}).then(async () => {
  const {origins = []} = await browser.permissions.getAll();
  const existing = await browser.scripting.getRegisteredContentScripts();
  if (existing.length) await browser.scripting.unregisterContentScripts({ids: existing.map(script => script.id)});
  if (!origins.length) return;
  await browser.scripting.registerContentScripts([
    {id: "hoist-content", matches: origins, js: ["content.js"], runAt: "document_start", world: "ISOLATED"},
    {id: "hoist-sender", matches: origins, js: ["sender.js"], runAt: "document_start", world: "MAIN"}
  ]);
  });
  return registration;
}
browser.runtime.onInstalled.addListener(registerSites);
browser.runtime.onStartup.addListener(registerSites);
browser.permissions.onRemoved.addListener(registerSites);
browser.permissions.onAdded.addListener(registerSites);

async function assertSite(sender) {
  if (!sender.tab || sender.frameId !== 0) throw new Error("Only the top-level page can connect to Hoist.");
  const origin = new URL(sender.url).origin;
  const page = new URL(sender.url);
  const pattern = page.protocol + "//" + page.hostname + "/*";
  if (!await browser.permissions.contains({origins: [pattern]})) throw new Error("Enable native Cast buttons for this site from Hoist’s toolbar popup first.");
  return origin;
}

async function requestSession(sender, appId) {
  const origin = await assertSite(sender);
  if ([...approvals.values()].some(item => item.tabId === sender.tab.id)) throw new Error("A device picker is already open.");
  const id = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => cancel(id, "Device selection timed out."), 90000);
    approvals.set(id, {resolve, reject, timer, tabId: sender.tab.id, origin, appId, windowId: null});
    browser.windows.create({url: browser.runtime.getURL("picker.html") + "?request=" + id, type: "popup", width: 390, height: 430}).then(window => {
      const approval = approvals.get(id);
      if (approval) approval.windowId = window.id;
    }).catch(error => cancel(id, error.message));
  });
}

function cancel(id, reason) {
  const pending = approvals.get(id);
  if (!pending) return;
  approvals.delete(id);
  clearTimeout(pending.timer);
  pending.reject(new Error(reason));
}
browser.windows.onRemoved.addListener(windowId => {
  for (const [id, item] of approvals) if (item.windowId === windowId) cancel(id, "Device selection cancelled.");
});
browser.tabs.onRemoved.addListener(tabId => sessions.delete(tabId));

async function pageCommand(message, sender) {
  const origin = await assertSite(sender);
  if (message.method === "availability") {
    const result = await native({action: "discover"});
    return {available: result.devices.length > 0};
  }
  if (message.method === "requestSession") return requestSession(sender, message.appId || "CC1AD845");
  const session = sessions.get(sender.tab.id);
  if (!session || session.origin !== origin || message.sessionId !== session.sessionId) throw new Error("Choose a screen through Hoist before controlling it.");
  if (message.method === "leave") { sessions.delete(sender.tab.id); return {}; }
  const now = Date.now();
  if (now - session.windowStart > 10000) { session.windowStart = now; session.requests = 0; }
  if (++session.requests > 80) throw new Error("This page is sending too many Cast requests.");
  const action = {sendMessage: "castMessage", loadMedia: "loadMedia", stopSession: "endSession", play: "resume", pause: "pause", stop: "stop", seek: "seek", volume: "volume", mute: "mute"}[message.method];
  if (!action) throw new Error("This Cast operation is not supported yet.");
  const current = await native({action: "status"});
  if (current.session?.sessionId !== session.sessionId) { sessions.delete(sender.tab.id); throw new Error("The receiver session changed. Connect again."); }
  const result = await native({action, sessionId: session.sessionId, namespace: message.namespace, data: message.data, media: message.media, autoplay: message.autoplay, currentTime: message.currentTime, position: message.position, value: message.value});
  if (action === "endSession") sessions.delete(sender.tab.id);
  return result;
}

async function handle(message, sender) {
  if (message?.kind === "page") return pageCommand(message, sender);
  if (!sender.url?.startsWith(browser.runtime.getURL(""))) throw new Error("Untrusted extension request.");
  if (message.kind === "scan") return native({action: "discover"});
  if (message.kind === "health") return native({action: "ping"});
  if (message.kind === "status") return native({action: "status"});
  if (message.kind === "enable") {
    await registerSites();
    await browser.scripting.executeScript({target: {tabId: message.tabId}, files: ["content.js"]});
    await browser.scripting.executeScript({target: {tabId: message.tabId}, files: ["sender.js"], world: "MAIN"});
    return {};
  }
  if (message.kind === "cast") {
    return native({action: "play", device: message.device, url: message.url});
  }
  if (message.kind === "control") {
    if (!["pause", "resume", "stop"].includes(message.action)) throw new Error("Unsupported control.");
    return native({action: message.action});
  }
  if (message.kind === "pickerInfo") {
    const item = approvals.get(message.request);
    if (!item) throw new Error("This request has expired.");
    return {origin: item.origin, appId: item.appId};
  }
  if (message.kind === "choose") {
    const item = approvals.get(message.request);
    if (!item) throw new Error("This request has expired.");
    const tab = await browser.tabs.get(item.tabId);
    if (new URL(tab.url).origin !== item.origin) throw new Error("The requesting page changed. Open the picker again.");
    const result = await native({action: "launch", device: message.device, appId: item.appId});
    const session = result.session;
    sessions.set(item.tabId, {...session, origin: item.origin, cursor: 0, windowStart: Date.now(), requests: 0});
    approvals.delete(message.request);
    clearTimeout(item.timer);
    item.resolve(result);
    if (item.windowId !== null) await browser.windows.remove(item.windowId);
    return {};
  }
  throw new Error("Unknown companion request.");
}
browser.runtime.onMessage.addListener((message, sender) => handle(message, sender).then(result => ({ok: true, result})).catch(error => ({ok: false, error: error.message})));

setInterval(async () => {
  for (const [tabId, session] of sessions) {
    if (pollBusy.has(tabId)) continue;
    pollBusy.add(tabId);
    try {
      const update = await native({action: "castEvents", sessionId: session.sessionId, after: session.cursor});
      for (const event of update.events) session.cursor = Math.max(session.cursor, event.sequence);
      await browser.tabs.sendMessage(tabId, {kind: "update", ...update});
    } catch (error) {
      sessions.delete(tabId);
      await browser.tabs.sendMessage(tabId, {kind: "ended", error: error.message}).catch(() => {});
    } finally { pollBusy.delete(tabId); }
  }
}, 1500);
