const id = new URL(location.href).searchParams.get("request");
const status = document.getElementById("status");
const devices = document.getElementById("devices");
const button = document.getElementById("connect");
async function call(message) {
  const reply = await browser.runtime.sendMessage(message);
  if (!reply.ok) throw new Error(reply.error);
  return reply.result;
}
(async () => {
  const info = await call({kind: "pickerInfo", request: id});
  document.getElementById("origin").textContent = info.origin;
  const result = await call({kind: "scan"});
  devices.replaceChildren(...result.devices.map(device => new Option(device.name, device.id)));
  button.disabled = !result.devices.length;
  if (!result.devices.length) status.textContent = "No screens found. Check Hoist and your Wi-Fi connection.";
})().catch(error => { status.textContent = error.message; status.classList.add("error"); });
button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Connecting…";
  try { await call({kind: "choose", request: id, device: devices.value}); }
  catch (error) { status.textContent = error.message; status.classList.add("error"); button.disabled = false; }
});
