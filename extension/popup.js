const $ = id => document.getElementById(id);
let tab;
function status(text, error = false) { $("status").textContent = text; $("status").classList.toggle("error", error); }
async function call(message) {
  const reply = await browser.runtime.sendMessage(message);
  if (!reply.ok) throw new Error(reply.error);
  return reply.result;
}
async function scan() {
  status("Looking for screens…");
  const {devices} = await call({kind: "scan"});
  $("devices").replaceChildren(...devices.map(device => new Option(device.name, device.id)));
  status(devices.length ? "Ready when you are." : "No screens found. Check Wi-Fi and Hoist’s Local Network access.");
}
function task(button, operation) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await operation(); } catch (error) { status(error.message, true); }
    finally { button.disabled = false; }
  });
}
task($("refresh"), scan);
task($("cast"), async () => {
  if (!$("devices").value) throw new Error("Choose a screen first.");
  status("Sending to your screen…");
  const result = await call({kind: "cast", device: $("devices").value, url: $("url").value.trim()});
  status(result.message);
});
for (const action of ["pause", "resume", "stop"]) task($(action), async () => {
  await call({kind: "control", action});
  status(action === "stop" ? "Playback stopped." : "Playback command sent.");
});
task($("enable"), async () => {
  if (!tab || !/^https?:/.test(tab.url)) throw new Error("Open a video website first.");
  const origin = new URL(tab.url).origin;
  const page = new URL(tab.url);
  const granted = await browser.permissions.request({origins: [page.protocol + "//" + page.hostname + "/*"]});
  if (!granted) throw new Error("Site access wasn’t granted.");
  await call({kind: "enable", tabId: tab.id});
  status("Enabled for " + origin + ". Reload this page. Native Cast support is experimental.");
});
(async () => {
  [tab] = await browser.tabs.query({active: true, currentWindow: true});
  if (tab && /^https?:/.test(tab.url)) {
    $("url").value = tab.url;
    if (!/(^|\.)youtube\.com$|^youtu\.be$/.test(new URL(tab.url).hostname)) {
      const results = await browser.scripting.executeScript({target: {tabId: tab.id}, func: () => [...document.querySelectorAll("video,audio")].map(media => media.currentSrc || media.src).find(url => /^https?:/.test(url)) || ""});
      if (results[0]?.result) $("url").value = results[0].result;
    }
  }
  await scan();
})().catch(error => status(error.message, true));
