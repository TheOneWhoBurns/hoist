# Preview validation

## Verified during development

- Native Swift app compiles for Apple Silicon with a macOS 13 deployment target.
- Bundled service starts without relying on a user-installed Python interpreter.
- System checks exercise the actual service process, request/reply framing, error replies and clean EOF shutdown.
- HTTP system checks transfer a full file, HEAD metadata and byte ranges; check suffix/open-ended ranges and reject invalid ranges, incorrect tokens and path traversal.
- A real Chromecast was discovered on the development network.
- A user-supplied YouTube link reached that Chromecast; the user confirmed seeing playback and asked to leave it running.

## Known limitation from the hardware test

The initial local-file test found that PyChromecast’s shared media controller could address the running YouTube receiver. Status belonged to the previous YouTube video, so it was not evidence that the local file played.

Hoist now requires the Default Media Receiver for local files/direct links, and waits for the requested content ID and a playing/paused state before reporting success. This correction has not yet been retested on the real TV because the user requested uninterrupted YouTube playback. Pause/seek commands from that first attempt affected the previous session and are not recorded as successful local-file tests.

## Still to verify

- Corrected local-file routing, actual decoding and all playback controls on a real receiver.
- YouTube playback through the packaged UI rather than the development helper.
- Direct URLs, live streams, audio files, multiple receiver models and reconnection behavior.
- Minimum supported macOS version and Intel architecture.
- Developer ID signing and notarization; current app is ad-hoc signed only.
- Full interactive UI check: native computer-use inspection timed out. The README image renders the actual SwiftUI view with illustrative device data.

## Firefox companion, 0.2

- Mozilla `web-ext lint`: zero errors and zero warnings.
- Packaged native host: native-endian length framing, request IDs, private Unix socket permissions, shared app communication, rejection of browser local-file requests, invalid-session rejection and clean shutdown all pass system checks.
- Actual Firefox 160 in a fresh temporary profile: extension load, MAIN-world sender API, isolated content bridge, native messaging, device discovery, basic framework context, Cast launcher and extension-owned picker cancellation all pass.
- No playback commands were sent by these companion checks. The user’s ongoing YouTube video was left untouched.
- The XPI is unsigned. Temporary installation works; permanent installation awaits Mozilla signing.
- Native buttons and playback on the live YouTube, Twitch, Prime Video, Netflix and F1 TV sites are not yet verified. The adapter is explicitly experimental.

## Discovery and popover fix, 0.2.1

- The app’s Local Network permission was disabled while command-line discovery had permission. Enabling Hoist’s macOS permission restored discovery in the running app.
- The popover now tracks SwiftUI preferred and intrinsic content size, sizes itself before opening, and opens after activation has settled. Opening an empty device list retries discovery.
- A live `--show --check-layout` run after rebuilding reported the real receiver in the app model and `fitsScreen: true`, including after discovery updated the UI.
- This verification sent no playback commands.

## Keyboard editing fix, 0.2.2

- Added the standard macOS Edit menu and responder-chain actions for paste, copy, cut, select all, undo and redo. The programmatically created accessory app previously had no Edit menu.
- Live UI checks confirmed pasting a sample URL, Command-A replacement and Command-Z restoring the previous URL. No test URL was submitted or cast.
- Redo is wired to Shift-Command-Z, but its final UI inspection timed out; it is not recorded as verified.
