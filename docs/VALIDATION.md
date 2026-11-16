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
