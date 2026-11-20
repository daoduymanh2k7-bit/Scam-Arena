/* Silero VAD runs locally. Only completed speech is uploaded by app-mode.js. */
(function (root) {
  "use strict";
  const ASSETS = "/vendor/vad/v0.0.31-ort1.22.0/";
  const SETTINGS = Object.freeze({
    model: "v5", positiveSpeechThreshold: 0.5, negativeSpeechThreshold: 0.35,
    redemptionMs: 550, preSpeechPadMs: 300, minSpeechMs: 96,
    submitUserSpeechOnPause: false, startOnLoad: false,
  });
  let libraryPromise;
  let preloadPromise;

  function script(src) {
    return new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      const timer = setTimeout(() => { tag.remove(); reject(new Error("VAD asset timeout")); }, 20000);
      tag.src = src;
      tag.onload = () => { clearTimeout(timer); resolve(); };
      tag.onerror = () => { clearTimeout(timer); tag.remove(); reject(new Error("VAD asset unavailable")); };
      document.head.append(tag);
    });
  }

  function loadLibrary() {
    if (!libraryPromise) {
      libraryPromise = (async () => {
        if (!root.ort) await script(ASSETS + "ort/ort.wasm.min.js");
        if (!root.vad) await script(ASSETS + "vad/bundle.min.js");
        if (!root.vad?.MicVAD) throw new Error("VAD library unavailable");
        return root.vad;
      })().catch((error) => { libraryPromise = null; throw error; });
    }
    return libraryPromise;
  }

  function preload() {
    if (!preloadPromise) preloadPromise = warmAssets().catch((error) => {
      preloadPromise = null;
      throw error;
    });
    return preloadPromise;
  }

  async function warmAssets() {
    await loadLibrary();
    // Warm HTTP cache only; never ask for microphone access here.
    await Promise.all(["vad/silero_vad_v5.onnx", "ort/ort-wasm-simd-threaded.wasm",
      "ort/ort-wasm-simd-threaded.mjs"].map(async (name) => {
      const response = await fetch(ASSETS + name, { cache: "force-cache" });
      if (!response.ok) throw new Error("VAD asset unavailable");
      await response.arrayBuffer();
    }));
  }

  class Capture {
    constructor(callbacks = {}, dependencies = {}) {
      this.callbacks = callbacks;
      this.deps = dependencies;
      this.context = dependencies.context || new (root.AudioContext || root.webkitAudioContext)();
      this.resuming = this.context.resume();
      // Avoid an unhandled rejection while the permission prompt is open.
      this.resuming.catch(() => {});
      this.enabled = false;
      this.ready = false;
      this.disposed = false;
      this.cycle = 0;
      this.activeCycle = -1;
      this.method = "Silero VAD v5";
      this.frameTail = Promise.resolve();
      this.transitions = Promise.resolve();
      this.pendingFrames = 0;
      this.initialization = null;
      this.maxTimer = null;
    }

    initialize() {
      if (!this.initialization) this.initialization = this._initialize();
      return this.initialization;
    }

    async _initialize() {
      await this.resuming;
      if (this.disposed) return;
      const getStream = this.deps.getStream || (() => navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      }));
      this.stream = await getStream();
      this._setTracks(false);
      if (this.disposed) { this._stopTracks(); return; }
      try {
        const factory = this.deps.createVad || (async (options) => (await loadLibrary()).MicVAD.new(options));
        this.vad = await factory({
          ...SETTINGS, baseAssetPath: ASSETS + "vad/", onnxWASMBasePath: ASSETS + "ort/",
          audioContext: this.context,
          getStream: async () => this.stream,
          pauseStream: async () => {},
          resumeStream: async () => this.stream,
          ortConfig: (ort) => { ort.env.wasm.numThreads = 1; ort.env.wasm.proxy = false; ort.env.logLevel = "error"; },
          onSpeechStart: () => this._startSpeech(),
          onSpeechEnd: (samples) => this._speech(samples, 16000),
          onVADMisfire: () => this._misfire(),
        });
        const process = this.vad.processFrame.bind(this.vad);
        // Serialize inference and discard frames from a previous listening turn.
        this.vad.processFrame = (frame) => this._queueFrame(() => process(frame));
        await this.vad.start();
        await this.vad.pause();
      } catch (error) {
        await this._disposeVad();
        if (this.disposed) return;
        this.method = "Mức âm lượng (dự phòng)";
        await this._initializeLegacy();
        this.callbacks.onFallback?.(error);
      }
      this.ready = !this.disposed;
    }

    _valid(cycle = this.eventCycle) {
      return !this.disposed && this.enabled && cycle === this.cycle && this.activeCycle === cycle;
    }

    _queueFrame(process) {
      const cycle = this.cycle;
      if (!this._valid(cycle) || this.flushing) return Promise.resolve();
      if (this.pendingFrames >= 10) {
        this._fail(new Error("VAD processing is too slow"));
        return Promise.resolve();
      }
      this.pendingFrames++;
      this.frameTail = this.frameTail.then(async () => {
        if (!this._valid(cycle)) return;
        this.eventCycle = cycle;
        try { await process(); } finally { this.eventCycle = null; }
      }).catch((error) => this._fail(error)).finally(() => { this.pendingFrames--; });
      return this.frameTail;
    }

    _startSpeech() {
      if (!this._valid()) return;
      clearTimeout(this.maxTimer);
      const cycle = this.cycle;
      this.maxTimer = setTimeout(() => this._flushLongSpeech(cycle), 14000);
      this.callbacks.onSpeechStart?.();
    }

    _speech(samples, rate) {
      if (!this._valid() || !samples?.length) return;
      const data = { samples, rate, capture_method: this.method };
      this.setEnabled(false); // Close the gate before starting upload/TTS.
      this.callbacks.onSpeech?.(data);
    }

    _misfire() {
      if (!this._valid()) return;
      clearTimeout(this.maxTimer);
      this.callbacks.onMisfire?.();
    }

    _flushLongSpeech(cycle) {
      if (!this.vad || !this._valid(cycle)) return;
      this.flushing = true;
      this.transitions = this.transitions.then(async () => {
        await this.frameTail;
        if (!this._valid(cycle)) { this.flushing = false; return; }
        this.eventCycle = cycle;
        this.vad.setOptions({ submitUserSpeechOnPause: true });
        try { await this.vad.pause(); } finally {
          this.vad.setOptions({ submitUserSpeechOnPause: false });
          this.eventCycle = null;
          this.flushing = false;
        }
        if (this._valid(cycle)) await this.vad.start();
      }).catch((error) => this._fail(error));
    }

    setEnabled(enabled) {
      if (this.disposed || this.enabled === enabled) return this.transitions;
      this.enabled = enabled;
      const cycle = ++this.cycle;
      this.activeCycle = -1;
      this._setTracks(enabled);
      clearTimeout(this.maxTimer);
      this.transitions = this.transitions.then(async () => {
        await this.initialize();
        await this.frameTail;
        if (this.disposed || cycle !== this.cycle) return;
        this.flushing = false;
        this._setTracks(this.enabled);
        if (this.vad) {
          await this.vad.pause();
          if (this.enabled && cycle === this.cycle) await this.vad.start();
        } else {
          this.node.port.postMessage({ enabled: this.enabled, cycle });
        }
        if (!this.disposed && cycle === this.cycle) this.activeCycle = cycle;
      }).catch((error) => this._fail(error));
      return this.transitions;
    }

    async _initializeLegacy() {
      if (this.deps.createLegacy) {
        this.node = await this.deps.createLegacy(this);
        return;
      }
      await this.context.audioWorklet.addModule("/js/call-mic-worklet.js?v=1");
      this.source = this.context.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.context, "scam-arena-call-mic", { channelCount: 1, channelCountMode: "explicit" });
      this.node.port.onmessage = ({ data }) => {
        if (!this._valid(data.cycle)) return;
        this.eventCycle = data.cycle;
        try {
          if (data.type === "speech-start") this._startSpeech();
          if (data.type === "speech") this._speech(data.samples, data.rate);
          if (data.type === "noise") this._misfire();
        } finally { this.eventCycle = null; }
      };
      this.source.connect(this.node);
      this.silent = this.context.createGain();
      this.silent.gain.value = 0;
      this.node.connect(this.silent).connect(this.context.destination);
    }

    _setTracks(enabled) { this.stream?.getAudioTracks().forEach((track) => { track.enabled = enabled; }); }
    _stopTracks() { this.stream?.getTracks().forEach((track) => track.stop()); }
    _fail(error) {
      if (this.disposed) return;
      this.setEnabled(false);
      this.callbacks.onError?.(error);
    }

    async _disposeVad() {
      if (!this.vad) return;
      try { await this.vad.destroy(); } catch {
        // Pinned vad-web 0.0.31 destroy assumes audio nodes were initialized.
        // A failed start still needs to release its ONNX session.
        await this.vad.model?.release?.();
      }
      this.vad = null;
    }

    destroy() {
      if (this.destroying) return this.destroying;
      this.disposed = true;
      this.enabled = false;
      this.cycle++;
      clearTimeout(this.maxTimer);
      this._stopTracks();
      this.destroying = (async () => {
        try { await this.initialization; } catch { /* clean a failed permission/init */ }
        await this.transitions;
        await this.frameTail;
        this._stopTracks();
        try { await this._disposeVad(); } finally {
          this.source?.disconnect();
          this.node?.disconnect();
          this.silent?.disconnect();
          if (this.context.state !== "closed") await this.context.close();
          this.ready = false;
        }
      })();
      return this.destroying;
    }
  }

  root.CallMicrophone = { Capture, preload, SETTINGS };
  if (typeof module !== "undefined" && module.exports) module.exports = root.CallMicrophone;
})(globalThis);
