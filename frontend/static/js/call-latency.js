/* Per-turn timings stay in this tab; no audio/text is logged or persisted here. */
(function (root) {
  "use strict";
  class CallLatency {
    constructor(capture = {}, clock = () => performance.now()) {
      this.clock = clock;
      this.started = Number.isFinite(capture.captured_at_ms) ? capture.captured_at_ms : clock();
      this.vad_ms = capture.vad_wait_ms;
    }
    async measure(stage, action) {
      const started = this.clock();
      try { return await action(); } finally { this[stage] = this.clock() - started; }
    }
    beginPlayback() { this.playRequested = this.clock(); }
    audioStarted() {
      if (this.total_ms !== undefined) return;
      const now = this.clock();
      this.play_ms = now - this.playRequested;
      this.total_ms = now - this.started + (Number.isFinite(this.vad_ms) ? this.vad_ms : 0);
    }
    description() {
      const ms = value => Number.isFinite(value) ? `${Math.round(Math.max(0, value))} ms` : "chưa đo được";
      const transport = Number.isFinite(this.stt_ms) && Number.isFinite(this.stt_server_ms)
        ? ms(this.stt_ms - this.stt_server_ms) : "chưa đo được";
      return `Chờ hết câu: ${ms(this.vad_ms)} (ước tính từ VAD)` +
        ` · Đóng gói WAV: ${ms(this.encode_ms)}` +
        ` · Gửi âm thanh và nhận chữ: ${ms(this.stt_ms)} (máy chủ: ${ms(this.stt_server_ms)}; HTTP còn lại ước tính: ${transport})` +
        ` · Xử lý hội thoại: ${ms(this.reply_ms)}` +
        ` · Tạo và tải giọng: ${ms(this.tts_ms)} (Piper: ${ms(this.tts_server_ms)})` +
        ` · Đệm phát: ${ms(this.play_ms)}` +
        ` · Tổng ${Number.isFinite(this.vad_ms) ? "từ khung tiếng nói cuối" : "từ lúc chốt đoạn"} đến phát: ${ms(this.total_ms)}`;
    }
  }
  root.CallLatency = CallLatency;
  if (typeof module !== "undefined" && module.exports) module.exports = CallLatency;
})(globalThis);
