# Hoist for Firefox

Cast from Firefox using the helper already bundled with the Hoist menu bar app.

## Install the development preview

1. Install and open **Hoist 0.2.0 or newer**. It automatically registers its Firefox native-messaging host when it launches. Keep the app open.
2. Download `Hoist-Firefox-0.2.0-unsigned.xpi` from [Releases](https://github.com/TheOneWhoBurns/hoist/releases).
3. In Firefox, open `about:debugging#/runtime/this-firefox`, select **Load Temporary Add-on**, and select the XPI. From a source checkout, you can select `extension/manifest.json` instead.
4. Click Hoist’s toolbar button. Choose your Chromecast and use **Cast video** for a YouTube URL or direct media link.

**This XPI is unsigned.** Normal permanent installation in release Firefox requires Mozilla signing. Temporary installation lasts until Firefox restarts. Do not disable extension-signature checks. The native helper is already in Hoist; do not install another Python runtime or helper.

Requires Firefox 142+ and the Hoist Mac app. Tested with a temporary profile in Firefox 160 on Apple Silicon.

## Native player buttons

On a video website, open the toolbar popup and select **Enable native Cast buttons on this site**. Approve Firefox’s site-access prompt, then reload that page.

The companion injects an experimental `chrome.cast` sender API and a subset of `cast.framework` at page startup. A compatible site can call its usual Cast API and open Hoist’s extension-owned device picker. Selecting a device authorizes that page to connect to the requested receiver app and control the session.

Closing the picker cancels the request. Leaving a browser session leaves the TV playing; stopping it explicitly stops the receiver app. Closing a browser tab does not stop your video.

## What is implemented

- Toolbar device discovery, current YouTube URL/direct HTML media detection, manual URL entry, and basic playback controls.
- Optional site access; no page injection until that site is enabled.
- Legacy sender initialization and availability callbacks, session creation, receiver volume/mute, custom namespace messages and incoming message listeners.
- Media loading, status updates, pause/resume/stop/seek and update listeners.
- A basic modern Cast context and `google-cast-launcher` element.
- Private native messaging into the running Hoist app; no LAN control port and no browser access to local file paths.

## Compatibility limits

This is an experimental API adapter, not a full Google Cast SDK implementation. A Cast-aware page may also gate functionality on browser identity, overwrite the injected SDK, require missing APIs, or use private authentication and DRM flows.

| Integration | Evidence |
| --- | --- |
| Actual Firefox → content bridge → native helper → Hoist | System-tested |
| Sender availability, framework context, launcher element, picker cancellation | System-tested in a controlled webpage |
| YouTube URLs through Hoist | Receiver playback verified in 0.1; extension transport verified separately |
| Native YouTube player Cast button | Not yet verified on the live website |
| Twitch, Prime Video, Netflix, F1 TV | Not verified or advertised as working |
| Queue editing, tracks/subtitles, full RemotePlayer API, DIAL | Not implemented |
| Ad blocking | Not included; browser filtering would not remove receiver-app ads |

The companion does not bypass DRM, copy login cookies, or automatically switch the TV on page load. A service-specific playback test is required before adding that service to a supported list.

## Troubleshooting

- **Native host not found:** open the new Hoist app once, then reopen the extension popup. Launching an old app copy can overwrite the registration; use one copy in Applications.
- **Open Hoist to connect:** the helper is installed but the app is not running, or an older version is running. Quit the old Hoist and open 0.2.0.
- **No devices:** check Local Network permissions, same-network connectivity and router multicast isolation.
- **The URL is unsupported:** use a YouTube video or a direct HTTP(S) media URL. `blob:` URLs are local to the browser and cannot be fetched by the TV.
- **Cast button still absent:** this site may require a different sender API or browser integration. Use the toolbar where the media source is supported; report the site and failure.

## Development and signing

```sh
npx web-ext lint --source-dir extension
bash scripts/build.sh
.venv/bin/python tests/native_system_check.py
.venv/bin/python tests/firefox_system_check.py
```

The Firefox system check uses a fresh temporary profile and the actual packaged native helper. It verifies the picker cancellation path and sends no playback commands. It temporarily registers the host manifest and restores its previous contents afterward. `HOIST_RUNTIME_DIR` isolates its Unix socket from the running app.

For a permanently installable XPI, obtain API credentials from [Mozilla’s developer hub](https://addons.mozilla.org/developers/addon/api/key/), and sign an unlisted distribution with `web-ext sign`. Supply credentials through environment variables or a secret store, never in source control. Publishing to the public add-ons directory is a separate distribution decision.

The native host is registered at `~/Library/Application Support/Mozilla/NativeMessagingHosts/io.github.theonewhoburns.hoist.json`. To uninstall the integration, remove the Firefox add-on and that manifest. Quit Hoist before deleting the app; a running app recreates registration on its next launch.
