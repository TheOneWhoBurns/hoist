(() => {
  if (window.__hoistSenderInstalled) return;
  window.__hoistSenderInstalled = true;
  const waiting = new Map();
  let configuration;
  let session = null;
  const rpc = request => new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timer = setTimeout(() => { waiting.delete(id); reject({code: "timeout", description: "Hoist did not respond."}); }, 100000);
    waiting.set(id, {resolve, reject, timer});
    window.postMessage({channel: "hoist:request", id, request}, location.origin);
  });
  const callbacks = (promise, success, failure) => promise.then(value => success?.(value)).catch(error => failure?.(error));
  const emit = (listeners, ...args) => {
    for (const listener of listeners) { try { listener(...args); } catch (error) { console.error("Hoist listener:", error); } }
  };
  class CastError {
    constructor(code, description = "", details = null) { Object.assign(this, {code, description, details}); }
  }
  class Volume { constructor(level = null, muted = null) { Object.assign(this, {level, muted}); } }
  class MediaInfo {
    constructor(contentId, contentType) { Object.assign(this, {contentId, contentType, streamType: "BUFFERED", metadata: null, duration: null, tracks: null, customData: null}); }
  }
  class LoadRequest {
    constructor(media) { Object.assign(this, {media, autoplay: true, currentTime: 0, customData: null}); }
  }
  class Media {
    constructor(owner, status = {}) {
      this.owner = owner;
      this.listeners = new Set();
      this.media = new MediaInfo("", "");
      this.supportedMediaCommands = ["pause", "seek", "stream_volume", "stream_mute"];
      this.volume = new Volume();
      this.update(status);
    }
    update(status) {
      this.currentTime = status.position || 0;
      this.playerState = status.state || "IDLE";
      this.mediaSessionId = status.mediaSessionId || 0;
      this.sessionId = this.owner.sessionId;
      this.media.contentId = status.contentId || this.media.contentId;
      this.media.contentType = status.contentType || this.media.contentType;
      this.media.duration = status.duration || 0;
      this.media.metadata = {title: status.title || ""};
      this.volume.level = status.volume ?? 0.5;
      this.updated = Date.now();
      emit(this.listeners, this.playerState !== "IDLE");
    }
    command(method, fields, success, failure) { callbacks(rpc({method, sessionId: this.sessionId, ...fields}), success, failure); }
    play(request, success, failure) { this.command("play", {}, success, failure); }
    pause(request, success, failure) { this.command("pause", {}, success, failure); }
    stop(request, success, failure) { this.command("stop", {}, success, failure); }
    seek(request, success, failure) { this.command("seek", {position: request.currentTime}, success, failure); }
    setVolume(request, success, failure) {
      const v = request.volume;
      this.command(v.muted != null ? "mute" : "volume", {value: v.muted != null ? v.muted : v.level}, success, failure);
    }
    getEstimatedTime() { return this.currentTime + (this.playerState === "PLAYING" ? (Date.now() - this.updated) / 1000 : 0); }
    addUpdateListener(listener) { this.listeners.add(listener); }
    removeUpdateListener(listener) { this.listeners.delete(listener); }
    supportsCommand(command) { return this.supportedMediaCommands.includes(command); }
    editTracksInfo(request, success, failure) { failure?.(new CastError("not_supported", "Track editing is not implemented in this preview.")); }
  }
  class Session {
    constructor(value) {
      Object.assign(this, value);
      this.media = [];
      this.senderApps = [];
      this.appImages = [];
      this.messages = new Map();
      this.listeners = new Set();
      this.mediaListeners = new Set();
    }
    addMessageListener(namespace, listener) {
      if (!this.messages.has(namespace)) this.messages.set(namespace, new Set());
      this.messages.get(namespace).add(listener);
    }
    removeMessageListener(namespace, listener) { this.messages.get(namespace)?.delete(listener); }
    addUpdateListener(listener) { this.listeners.add(listener); }
    removeUpdateListener(listener) { this.listeners.delete(listener); }
    addMediaListener(listener) { this.mediaListeners.add(listener); }
    removeMediaListener(listener) { this.mediaListeners.delete(listener); }
    sendMessage(namespace, data, success, failure) {
      try {
        if (typeof data === "string") data = JSON.parse(data);
        callbacks(rpc({method: "sendMessage", sessionId: this.sessionId, namespace, data}), success, failure);
      } catch (error) { failure?.(new CastError("invalid_parameter", error.message)); }
    }
    loadMedia(request, success, failure) {
      callbacks(rpc({method: "loadMedia", sessionId: this.sessionId, ...request}).then(result => {
        const media = new Media(this, result.status);
        media.media = request.media;
        this.media = [media];
        emit(this.mediaListeners, media);
        return media;
      }), success, failure);
    }
    setReceiverVolumeLevel(value, success, failure) { callbacks(rpc({method: "volume", sessionId: this.sessionId, value}), success, failure); }
    setReceiverMuted(value, success, failure) { callbacks(rpc({method: "mute", sessionId: this.sessionId, value}), success, failure); }
    stop(success, failure) { callbacks(rpc({method: "stopSession", sessionId: this.sessionId}).then(() => end()), success, failure); }
    leave(success, failure) { callbacks(rpc({method: "leave", sessionId: this.sessionId}).then(() => end()), success, failure); }
    getSessionId() { return this.sessionId; }
    getCastDevice() { return {...this.receiver, deviceId: this.receiver.label}; }
    getMediaSession() { return this.media[0] || null; }
    getSessionState() { return this.status === "connected" ? "SESSION_STARTED" : "SESSION_ENDED"; }
    getSessionObj() { return this; }
    getApplicationMetadata() { return {name: this.displayName, applicationId: this.appId, images: []}; }
    endSession(stopCasting) { stopCasting ? this.stop() : this.leave(); }
    addEventListener(type, listener) { this.addUpdateListener(listener); }
    removeEventListener(type, listener) { this.removeUpdateListener(listener); }
  }
  const frameworkListeners = new Map();
  function frameworkEvent(type, detail) { emit(frameworkListeners.get(type) || [], {type, ...detail}); }
  function end() {
    if (session) { session.status = "disconnected"; emit(session.listeners, false); }
    session = null;
    frameworkEvent("sessionstatechanged", {sessionState: "SESSION_ENDED"});
    frameworkEvent("caststatechanged", {castState: "NOT_CONNECTED"});
  }
  async function connect(request) {
    const result = await rpc({method: "requestSession", appId: request?.appId || configuration?.sessionRequest?.appId || "CC1AD845"});
    session = new Session(result.session);
    configuration?.sessionListener?.(session);
    frameworkEvent("sessionstatechanged", {sessionState: "SESSION_STARTED", session});
    frameworkEvent("caststatechanged", {castState: "CONNECTED"});
    return session;
  }
  window.addEventListener("message", event => {
    if (event.source !== window || event.origin !== location.origin) return;
    const message = event.data;
    if (message?.channel === "hoist:reply") {
      const request = waiting.get(message.id);
      if (!request) return;
      clearTimeout(request.timer);
      waiting.delete(message.id);
      message.ok ? request.resolve(message.result) : request.reject(new CastError("session_error", message.error));
    }
    if (message?.channel === "hoist:event" && session) {
      if (message.kind === "ended") { end(); return; }
      if (message.session?.sessionId !== session.sessionId) { end(); return; }
      Object.assign(session, message.session);
      if (message.status) {
        if (!session.media.length && message.status.contentId) {
          const media = new Media(session, message.status);
          session.media = [media];
          emit(session.mediaListeners, media);
        } else session.media[0]?.update(message.status);
      }
      for (const incoming of message.events || []) emit(session.messages.get(incoming.namespace) || [], incoming.namespace, JSON.stringify(incoming.data));
      emit(session.listeners, true);
    }
  });
  const enumeration = values => Object.fromEntries(values.map(value => [value.toUpperCase(), value]));
  const cast = {
    isAvailable: true,
    VERSION: [1, 2],
    Error: CastError, Session, Volume,
    ApiConfig: class { constructor(sessionRequest, sessionListener, receiverListener, autoJoinPolicy = "tab_and_origin_scoped", defaultActionPolicy = "create_session") { Object.assign(this, {sessionRequest, sessionListener, receiverListener, autoJoinPolicy, defaultActionPolicy}); } },
    SessionRequest: class { constructor(appId, capabilities = [], timeout = 100000) { Object.assign(this, {appId, capabilities, requestSessionTimeout: timeout}); } },
    Image: class { constructor(url) { this.url = url; this.width = null; this.height = null; } },
    Receiver: class { constructor(label, friendlyName) { Object.assign(this, {label, friendlyName, capabilities: ["video_out", "audio_out"], receiverType: "cast", volume: new Volume()}); } },
    AutoJoinPolicy: enumeration(["tab_and_origin_scoped", "origin_scoped", "page_scoped"]),
    DefaultActionPolicy: enumeration(["create_session", "cast_this_tab"]),
    ReceiverAvailability: enumeration(["available", "unavailable"]),
    SessionStatus: enumeration(["connected", "disconnected", "stopped"]),
    Capability: enumeration(["video_out", "audio_out", "video_in", "audio_in"]),
    ReceiverType: enumeration(["cast", "dial", "custom"]),
    ErrorCode: enumeration(["cancel", "timeout", "api_not_initialized", "invalid_parameter", "extension_not_compatible", "extension_missing", "receiver_unavailable", "session_error", "channel_error", "load_media_failed"]),
    timeout: {requestSession: 100000, sendCustomMessage: 45000},
    initialize(config, success, failure) {
      configuration = config;
      callbacks(rpc({method: "availability"}).then(result => {
        config.receiverListener?.(result.available ? "available" : "unavailable");
        frameworkEvent("caststatechanged", {castState: result.available ? "NOT_CONNECTED" : "NO_DEVICES_AVAILABLE"});
      }), success, failure);
    },
    requestSession(success, failure, request) { callbacks(connect(request), success, failure); },
    requestSessionById() { throw new CastError("not_supported", "Use the Hoist picker to approve a session."); },
    logMessage() {},
    media: {
      DEFAULT_MEDIA_RECEIVER_APP_ID: "CC1AD845", MediaInfo, LoadRequest, Media,
      PlayerState: {IDLE: "IDLE", PLAYING: "PLAYING", PAUSED: "PAUSED", BUFFERING: "BUFFERING"},
      StreamType: {BUFFERED: "BUFFERED", LIVE: "LIVE", OTHER: "OTHER"},
      ResumeState: {PLAYBACK_START: "PLAYBACK_START", PLAYBACK_PAUSE: "PLAYBACK_PAUSE"},
      MetadataType: {GENERIC: 0, MOVIE: 1, TV_SHOW: 2, MUSIC_TRACK: 3, PHOTO: 4},
      MediaCommand: enumeration(["pause", "seek", "stream_volume", "stream_mute"]),
      IdleReason: {CANCELLED: "CANCELLED", INTERRUPTED: "INTERRUPTED", FINISHED: "FINISHED", ERROR: "ERROR"},
      timeout: {load: 45000, play: 45000, pause: 45000, stop: 45000, seek: 45000},
      SeekRequest: class { constructor() { this.currentTime = 0; this.resumeState = null; } },
      VolumeRequest: class { constructor(volume) { this.volume = volume; } },
      PlayRequest: class {}, PauseRequest: class {}, StopRequest: class {},
      GenericMediaMetadata: class { constructor() { this.metadataType = 0; } },
      MovieMediaMetadata: class { constructor() { this.metadataType = 1; } },
      TvShowMediaMetadata: class { constructor() { this.metadataType = 2; } },
      MusicTrackMediaMetadata: class { constructor() { this.metadataType = 3; } }
    }
  };
  window.chrome = window.chrome || {};
  window.chrome.cast = cast;
  const context = {
    setOptions(options) { cast.initialize(new cast.ApiConfig(new cast.SessionRequest(options.receiverApplicationId), () => {}, () => {})); },
    requestSession() { return connect(); },
    getCurrentSession() { return session; },
    getCastState() { return session ? "CONNECTED" : "NOT_CONNECTED"; },
    getSessionState() { return session ? "SESSION_STARTED" : "NO_SESSION"; },
    endCurrentSession(stopCasting) { session?.endSession(stopCasting); },
    addEventListener(type, listener) { if (!frameworkListeners.has(type)) frameworkListeners.set(type, new Set()); frameworkListeners.get(type).add(listener); },
    removeEventListener(type, listener) { frameworkListeners.get(type)?.delete(listener); }
  };
  window.cast = window.cast || {};
  window.cast.framework = {
    CastContext: {getInstance: () => context},
    CastContextEventType: {CAST_STATE_CHANGED: "caststatechanged", SESSION_STATE_CHANGED: "sessionstatechanged"},
    CastState: {NO_DEVICES_AVAILABLE: "NO_DEVICES_AVAILABLE", NOT_CONNECTED: "NOT_CONNECTED", CONNECTING: "CONNECTING", CONNECTED: "CONNECTED"},
    SessionState: {NO_SESSION: "NO_SESSION", SESSION_STARTING: "SESSION_STARTING", SESSION_STARTED: "SESSION_STARTED", SESSION_START_FAILED: "SESSION_START_FAILED", SESSION_ENDED: "SESSION_ENDED"}
  };
  if (!customElements.get("google-cast-launcher")) customElements.define("google-cast-launcher", class extends HTMLElement {
    connectedCallback() {
      if (this.shadowRoot) return;
      const root = this.attachShadow({mode: "open"});
      const button = document.createElement("button");
      button.textContent = "Cast";
      button.setAttribute("aria-label", "Cast with Hoist");
      button.style.cssText = "font:inherit;color:inherit;background:transparent;border:1px solid currentColor;border-radius:4px;padding:6px 10px;cursor:pointer";
      button.onclick = () => connect().catch(error => { button.title = error.description; });
      root.append(button);
    }
  });
  const previous = window.__onGCastApiAvailable;
  let callback = previous;
  try {
    Object.defineProperty(window, "__onGCastApiAvailable", {configurable: true, get: () => callback, set: value => {
      callback = value;
      if (typeof value === "function") queueMicrotask(() => value(true));
    }});
  } catch (_) {}
  if (typeof previous === "function") queueMicrotask(() => previous(true));
  window.dispatchEvent(new CustomEvent("hoist:available"));
})();
