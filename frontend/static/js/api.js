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
    scammerReply(scenarioKey, history, userText) {
      return fetch("/api/arena/reply", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_key: scenarioKey, history, user_text: userText }),
      }).then(asJson);
    },
    scoreSession(sessionId, scenarioType, transcript) {
      return fetch("/api/arena/score", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, scenario_type: scenarioType, transcript }),
      }).then(asJson);
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
