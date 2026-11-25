const Api = (() => {
  async function asJson(response) {
    if (!response.ok) {
      let detail = response.statusText;
      try { detail = (await response.json()).detail || detail; } catch (_) { /* empty response */ }
      const error = new Error(detail);
      error.status = response.status;
      error.retryAfterMs = Number(response.headers.get("Retry-After")) * 1000;
      throw error;
    }
    return response.json();
  }

  return {
    listScenarios: () => fetch("/api/arena/scenarios").then(asJson),
    listCallerVoices: () => fetch("/api/voice/caller-voices").then(asJson),
    randomScenario: () => fetch("/api/arena/scenarios/random").then(asJson),
    startCall(scenarioKey, interactionMode = "message", practiceDifficulty = 'adaptive', exerciseMode = 'training') {
      return fetch("/api/arena/calls", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_key: scenarioKey, interaction_mode: interactionMode, practice_difficulty: practiceDifficulty, exercise_mode: exerciseMode }),
      }).then(asJson);
    },
    submitCallTurn(sessionId, userText, elapsedSeconds) {
      return fetch(`/api/arena/calls/${encodeURIComponent(sessionId)}/turn`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_text: userText, elapsed_seconds: elapsedSeconds }),
      }).then(asJson);
    },
    regenerateLine(sessionId, turnNo, lineId) {
      const query = lineId == null ? "" : `?line_id=${encodeURIComponent(lineId)}`;
      return fetch(`/api/arena/calls/${encodeURIComponent(sessionId)}/turns/${turnNo}/regenerate${query}`, { method: "POST" }).then(asJson);
    },
    likeLine(sessionId, turnNo, lineId) {
      return fetch(`/api/arena/calls/${encodeURIComponent(sessionId)}/turns/${turnNo}/lines/${lineId}/like`, { method: "POST" }).then(asJson);
    },
    finishCall(sessionId) {
      return fetch(`/api/arena/calls/${encodeURIComponent(sessionId)}/finish`, { method: "POST" })
        .then((response) => {
          if (!response.ok) throw new Error(response.statusText || "Không thể kết thúc phiên gọi.");
          return null;
        });
    },
    callSummary(sessionId) {
      return fetch(`/api/arena/calls/${encodeURIComponent(sessionId)}/summary`).then(asJson);
    },
    callHistory() { return fetch("/api/arena/history?limit=30").then(asJson); },
    messageHistory() { return fetch('/api/arena/history?limit=100&interaction_mode=message').then(asJson); },
    callTranscript(sessionId) {
      return fetch(`/api/arena/calls/${encodeURIComponent(sessionId)}/transcript`).then(asJson);
    },
    async transcribeAudio(blob) {
      const form = new FormData();
      form.append("audio", blob, blob.type === "audio/wav" ? "recording.wav" : "recording.webm");
      return fetch("/api/voice/transcribe", { method: "POST", body: form }).then(asJson);
    },
    async transcribePartial(blob, signal) {
      const form = new FormData();
      form.append("audio", blob, "partial.wav");
      return fetch("/api/voice/transcribe/partial", { method: "POST", body: form, signal }).then(asJson);
    },
    async speakText(text, voiceId = null, timing = null, signal = undefined) {
      const query = voiceId ? `?voice=${encodeURIComponent(voiceId)}` : "";
      const response = await fetch(`/api/voice/speak${query}`, {
        signal,
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!response.ok) {
        let detail = "Không tạo được giọng đọc.";
        try { detail = (await response.json()).detail || detail; } catch (_) { /* empty response */ }
        throw new Error(detail);
      }
      const audio = await response.blob();
      const duration = response.headers.get("Server-Timing")?.match(/(?:^|,)\s*tts;dur=([\d.]+)/)?.[1];
      if (timing && duration !== undefined) timing.tts_server_ms = Number(duration);
      return audio;
    },
  };
})();
