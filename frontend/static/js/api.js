const Api = (() => {
  async function asJson(response) {
    if (!response.ok) {
      let detail = response.statusText;
      try { detail = (await response.json()).detail || detail; } catch (_) { /* empty response */ }
      throw new Error(detail);
    }
    return response.json();
  }

  return {
    listScenarios: () => fetch("/api/arena/scenarios").then(asJson),
    randomScenario: () => fetch("/api/arena/scenarios/random").then(asJson),
    startCall(scenarioKey) {
      return fetch("/api/arena/calls", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_key: scenarioKey }),
      }).then(asJson);
    },
    submitCallTurn(sessionId, userText, elapsedSeconds) {
      return fetch(`/api/arena/calls/${encodeURIComponent(sessionId)}/turn`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_text: userText, elapsed_seconds: elapsedSeconds }),
      }).then(asJson);
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
    callTranscript(sessionId) {
      return fetch(`/api/arena/calls/${encodeURIComponent(sessionId)}/transcript`).then(asJson);
    },
    flagCallTurn(sessionId, turnNo) {
      return fetch(`/api/arena/calls/${encodeURIComponent(sessionId)}/turns/${turnNo}/flag`, { method: "POST" }).then(asJson);
    },
    intentCandidates() { return fetch("/api/arena/admin/intent-candidates").then(asJson); },
    approveIntentCandidate(candidateId, intent, phrase) {
      return fetch(`/api/arena/admin/intent-candidates/${candidateId}/approve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ intent, phrase }),
      }).then(asJson);
    },
    rejectIntentCandidate(candidateId) {
      return fetch(`/api/arena/admin/intent-candidates/${candidateId}/reject`, { method: "POST" }).then(asJson);
    },
    async transcribeAudio(blob) {
      const form = new FormData();
      form.append("audio", blob, "recording.webm");
      return fetch("/api/voice/transcribe", { method: "POST", body: form }).then(asJson);
    },
    async speakText(text) {
      const response = await fetch("/api/voice/speak", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!response.ok) {
        let detail = "Không tạo được giọng đọc.";
        try { detail = (await response.json()).detail || detail; } catch (_) { /* empty response */ }
        throw new Error(detail);
      }
      return response.blob();
    },
  };
})();
