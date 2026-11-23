/* One draft request in flight, no request backlog, stale responses never update UI. */
(function (root) {
  "use strict";
  class PartialSpeech {
    constructor(request, onText, onUnavailable = () => {}) {
      this.request = request;
      this.onText = onText;
      this.onUnavailable = onUnavailable;
      this.generation = 0;
      this.available = true;
    }
    start() { this.stop(); this.active = this.available; }
    stop() {
      this.active = false;
      this.generation++;
      this.controller?.abort();
      this.controller = null;
      this.busy = false;
    }
    async offer(data) {
      if (!this.active || this.busy) return;
      const generation = this.generation;
      this.busy = true;
      const controller = new AbortController();
      this.controller = controller;
      try {
        const result = await this.request(data, controller.signal);
        if (this.active && generation === this.generation && result.text?.trim()) this.onText(result.text.trim());
      } catch (error) {
        if (!this.active || generation !== this.generation || error.name === "AbortError") return;
        if (error.status !== 429) {
          this.available = false;
          this.active = false;
          this.onUnavailable();
        }
      } finally {
        if (generation === this.generation) { this.busy = false; this.controller = null; }
      }
    }
  }
  root.PartialSpeech = PartialSpeech;
  if (typeof module !== "undefined" && module.exports) module.exports = PartialSpeech;
})(globalThis);
