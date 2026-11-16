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

The 0.2 preview now includes native messaging, a toolbar action, per-site injection, an extension-owned picker and an initial sender API adapter. These have been exercised in a real Firefox system check. Permanent-install signing and service-specific playback verification remain open.

The intended experience is the native Cast button on compatible websites, with Hoist providing the device picker and session connection. This is a real Cast sender API compatibility project, not just a toolbar button that forwards URLs.

1. Sign the companion for normal Firefox installation. Protocol version 2 and app-owned host registration are implemented; the host allows only the companion extension ID and exposes no LAN control endpoint.
2. Verify toolbar playback end-to-end on each supported receiver. Direct media and YouTube forwarding are implemented, with optional per-site API injection.
3. Expand the sender API adapter beyond its initial lifecycle, namespace relay and media controls. Browser identity detection and missing modern RemotePlayer/queue/track APIs require further work.
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
