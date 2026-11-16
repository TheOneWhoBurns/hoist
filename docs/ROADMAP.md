# Small app. Deliberate scope.

Hoist stays a menu bar app. The desktop app owns device discovery, media serving and receiver sessions. A browser companion will connect to it, not introduce another separately installed helper.

## Preview to reliable file casting

- Retest the corrected Default Media Receiver routing on real hardware, including switching away from YouTube.
- Verify pause, resume, seeking, volume, end-of-file, device loss, network changes and sleep/wake.
- Test current Chromecast generations and Google TV receivers.
- Add codec inspection, clear unsupported-format errors and optional bundled transcoding.
- Add subtitles, a small queue and a launch-at-login preference.
- Sign and notarize releases with an Apple Developer ID; validate the minimum macOS version and Intel packaging.

## Firefox companion

The intended experience is the native Cast button on compatible websites, with Hoist providing the device picker and session connection. This is a real Cast sender API compatibility project, not just a toolbar button that forwards URLs.

1. Define a versioned native-messaging protocol and register the native host from the app. Accept messages only from the signed companion extension ID; do not expose a LAN control endpoint.
2. Start with an explicit toolbar action for direct media and verified YouTube links, with per-site permission requests.
3. Implement the required sender API lifecycle: availability, initialization, session requests, namespace messages, media status and disconnect handling. Browser identity detection may require service-specific work.
4. Add native player integration one service at a time. For YouTube, Twitch, Prime Video, Netflix and F1 TV, record receiver IDs, authentication needs, supported API surface and a reproducible playback test. A Cast icon alone is not a pass.
5. Publish an honest compatibility matrix and make unsupported sites fail clearly. Protected services may require cooperation from their provider; do not promise DRM playback or bypass it.

Firefox requires an explicit extension installation. Hoist can guide that step from onboarding, but must not silently install or weaken extension-signing protections.

## Ad blocking

- Explore optional browser-side request filtering with narrow permissions and transparent filter sources.
- Evaluate direct playback for supported public media where permitted by the source and technically feasible.
- Distinguish browser ads from ads fetched by a Cast receiver: browser filters do not follow playback into YouTube, Netflix or another TV app.
- Do not advertise ad-free streaming services without repeatable end-to-end evidence. Local-file playback has no advertising.

## Product principles

One app bundle. A compact menu bar surface. No accounts or telemetry. No subscription required to cast your own files. Clear errors instead of false success. Service compatibility earned by testing.
