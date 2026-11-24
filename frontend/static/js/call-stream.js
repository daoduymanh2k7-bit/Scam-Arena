/* One bounded socket per utterance. Final transcripts alone may trigger a turn. */
(function (root) {
  "use strict";
  class CallStream {
    constructor(onDraft, dependencies = {}) {
      this.onDraft = onDraft;
      this.createSocket = dependencies.createSocket || (() => new WebSocket(
        `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/voice/transcribe/stream`));
      this.failed = false;
    }
    start() {
      this.cancel();
      if (this.failed) return;
      const session = { queue: [], bytes: 0, ready: false, finishing: false, closed: false };
      this.session = session;
      session.result = new Promise((resolve, reject) => { session.resolve = resolve; session.reject = reject; });
      // Speech can continue after a handshake failure; consume rejection immediately.
      session.result.catch(() => {});
      const fail = () => { this.failed = true; this.close(session, new Error("Streaming unavailable")); };
      try {
        session.socket = this.createSocket();
        session.socket.onmessage = ({ data }) => {
          if (session.closed || this.session !== session) return;
          let event;
          try { event = JSON.parse(data); } catch { fail(); return; }
          if (event.type === "ready") {
            clearTimeout(session.timer);
            session.ready = true;
            for (const bytes of session.queue) session.socket.send(bytes);
            session.queue = [];
            if (session.finishing) this.flush(session);
          } else if (event.type === "draft" && !session.finishing) {
            this.onDraft(event.text);
          } else if (event.type === "final" && session.finishing && typeof event.text === "string" && event.text.trim()) {
            this.close(session, null, event);
          } else if (event.type === "error" || event.type === "final") fail();
        };
        session.socket.onerror = fail;
        session.socket.onclose = () => { if (!session.closed) fail(); };
        session.timer = setTimeout(fail, 6000);
      } catch { fail(); }
    }
    offer(samples) {
      const session = this.session;
      if (!session || session.closed || session.finishing) return;
      const bytes = new ArrayBuffer(samples.length * 2);
      const view = new DataView(bytes);
      for (let i = 0; i < samples.length; i++) {
        const value = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(i * 2, Math.round(value * 32767), true);
      }
      session.bytes += bytes.byteLength;
      if (session.bytes > 30 * 32000 || session.socket.bufferedAmount > 128000) {
        this.failed = true;
        this.close(session, new Error("Streaming backpressure"));
        return;
      }
      if (session.ready) session.socket.send(bytes);
      else session.queue.push(bytes);
    }
    finish() {
      const session = this.session;
      if (!session || session.closed) return Promise.reject(new Error("No stream"));
      session.finishing = true;
      if (session.ready) this.flush(session);
      return session.result;
    }
    flush(session) {
      session.socket.send('{"type":"finish"}');
      clearTimeout(session.timer);
      session.timer = setTimeout(() => {
        this.failed = true;
        this.close(session, new Error("Streaming final timeout"));
      }, 7000);
    }
    close(session, error, result) {
      if (session.closed) return;
      session.closed = true;
      clearTimeout(session.timer);
      session.queue = [];
      if (this.session === session) this.session = null;
      if (error) session.reject(error); else session.resolve(result);
      session.socket?.close();
    }
    cancel() {
      if (this.session) this.close(this.session, new Error("Stream cancelled"));
    }
  }
  root.CallStream = CallStream;
  if (typeof module !== "undefined" && module.exports) module.exports = CallStream;
})(globalThis);
