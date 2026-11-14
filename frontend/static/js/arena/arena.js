(() => {
  const $ = (id) => document.getElementById(id);
  const picker = $("arena-picker"), session = $("arena-session"), result = $("arena-result");
  const scenarioList = $("arena-scenario-list"), transcriptBox = $("arena-transcript");
  const textInput = $("arena-text-input"), micButton = $("arena-mic-btn");
  const sendButton = $("arena-send-btn"), status = $("arena-status");
  const audioPlayer = $("arena-audio-player");
  let scenario = null, sessionId = null, mediaRecorder = null, chunks = [];
  let recording = false, busy = false, callEnded = false, lastScammerAt = null;
  let timerStartedAt = null, timerHandle = null;

  function setStatus(message) { status.textContent = message || ""; }
  function setBusy(value) {
    busy = value;
    sendButton.disabled = value;
    textInput.disabled = value;
    micButton.disabled = value || callEnded;
  }
  function addBubble(text, role) {
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role === "user" ? "user" : "scammer"}`;
    bubble.textContent = text;
    transcriptBox.appendChild(bubble);
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  }
  function setCallTimer() {
    clearInterval(timerHandle);
    timerStartedAt = Date.now();
    const timer = $("arena-call-timer");
    timerHandle = setInterval(() => {
      const seconds = Math.floor((Date.now() - timerStartedAt) / 1000);
      timer.textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    }, 1000);
  }
  async function speak(text) {
    try {
      const blob = await Api.speakText(text);
      const url = URL.createObjectURL(blob);
      audioPlayer.src = url;
      await audioPlayer.play();
      await new Promise((resolve) => {
        audioPlayer.onended = resolve;
        audioPlayer.onerror = resolve;
      });
      URL.revokeObjectURL(url);
    } catch (error) {
      setStatus("Chưa phát được giọng đọc; bạn vẫn có thể đọc lời thoại trên màn hình.");
    }
    lastScammerAt = Date.now();
  }
  function updateCallState(response) {
    if (response.ended) {
      callEnded = true;
      micButton.disabled = true;
      sendButton.disabled = true;
      textInput.disabled = true;
    }
  }
  async function showScammer(response) {
    const line = response.bot_text;
    if (!line) return;
    addBubble(line, "scammer");
    updateCallState(response);
    setStatus("Đang phát lời thoại…");
    await speak(line);
    if (!callEnded && response.intent === "unknown") {
      setStatus("Chưa nhận diện rõ ý định. Hãy thử nói rõ bạn từ chối, muốn tự xác minh, nghi ngờ, hay đồng ý làm theo.");
    } else if (callEnded) {
      setStatus("Cuộc gọi đã kết thúc. Xem kết quả để đọc bài học và phản hồi.");
    } else if (!callEnded) {
      const source = response.intent_method === "rasa"
        ? "Rasa đã phân loại câu trả lời. "
        : response.intent_method === "rule"
          ? "Luật an toàn/dự phòng đã nhận diện câu trả lời. "
          : "";
      setStatus(`${source}Đến lượt bạn. Hãy bình tĩnh trả lời hoặc yêu cầu xác minh.`);
    }
  }
  async function startSession(nextScenario) {
    scenario = nextScenario;
    sessionId = null;
    callEnded = false;
    picker.hidden = true;
    result.hidden = true;
    session.hidden = false;
    $("arena-scenario-label").textContent = scenario.label;
    transcriptBox.replaceChildren();
    textInput.value = "";
    setBusy(true);
    setCallTimer();
    setStatus("Đang kết nối…");
    try {
      const response = await Api.startCall(scenario.key);
      sessionId = response.session_id;
      await showScammer(response);
    } catch (error) {
      setStatus(`Không tải được lời thoại: ${error.message}`);
    } finally { setBusy(false); }
  }
  async function sendReply(text, elapsed) {
    const answer = text.trim();
    if (!answer || busy || callEnded || !scenario) return;
    setBusy(true);
    setStatus("Đang xử lý câu trả lời…");
    try {
      const response = await Api.submitCallTurn(sessionId, answer, elapsed);
      addBubble(answer, "user");
      textInput.value = "";
      await showScammer(response);
    } catch (error) {
      setStatus(`Chưa gửi được câu trả lời: ${error.message}`);
    } finally { setBusy(false); }
  }
  async function loadScenarios() {
    try {
      const scenarios = await Api.listScenarios();
      scenarios.forEach((item) => {
        const button = document.createElement("button");
        button.className = "scenario-card";
        button.type = "button";
        const label = document.createElement("strong");
        label.textContent = item.label;
        const hint = document.createElement("span");
        hint.textContent = "Bắt đầu tình huống giả lập →";
        button.append(label, hint);
        button.addEventListener("click", () => startSession(item));
        scenarioList.appendChild(button);
      });
    } catch (error) {
      $("picker-error").hidden = false;
      $("picker-error").textContent = `Không tải được danh sách tình huống: ${error.message}`;
    }
  }
  async function toggleRecording() {
    if (recording) {
      recording = false;
      micButton.textContent = "🎙 Đang nhận diện…";
      const elapsed = lastScammerAt ? Math.max(0, (Date.now() - lastScammerAt) / 1000) : null;
      const stopped = new Promise((resolve) => mediaRecorder.addEventListener("stop", resolve, { once: true }));
      mediaRecorder.stop();
      await stopped;
      mediaRecorder.stream.getTracks().forEach((track) => track.stop());
      try {
        const { text } = await Api.transcribeAudio(new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" }));
        if (!text.trim()) throw new Error("Không nhận diện được lời nói.");
        micButton.textContent = "🎙 Ghi âm";
        await sendReply(text, elapsed);
      } catch (error) {
        setStatus(`Nhận diện thất bại: ${error.message}`);
        micButton.textContent = "🎙 Ghi âm";
      }
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      mediaRecorder = new MediaRecorder(stream);
      mediaRecorder.addEventListener("dataavailable", (event) => { if (event.data.size) chunks.push(event.data); });
      mediaRecorder.start();
      recording = true;
      micButton.textContent = "⏹ Dừng ghi âm";
      setStatus("Đang ghi âm… bấm dừng khi nói xong.");
    } catch (error) {
      setStatus(`Không truy cập được micro: ${error.message}`);
    }
  }
  async function finishSession() {
    if (recording) {
      setStatus("Hãy dừng ghi âm trước khi kết thúc phiên.");
      return;
    }
    clearInterval(timerHandle);
    session.hidden = true;
    result.hidden = false;
    $("arena-score").textContent = "…";
    $("arena-badge").textContent = "Đang tính điểm";
    try {
      await Api.finishCall(sessionId);
      const score = await Api.callSummary(sessionId);
      $("arena-score").textContent = String(score.total_score);
      $("arena-badge").textContent = score.badge || "Kết quả luyện tập";
      $("arena-latency").textContent = score.avg_response_latency == null
        ? "Chưa có dữ liệu thời gian phản hồi."
        : `Thời gian phản hồi trung bình: ${score.avg_response_latency.toFixed(1)} giây (chỉ là chỉ số tham khảo).`;
      const list = $("arena-mistakes");
      list.replaceChildren();
      (score.mistakes || []).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = `${item.severity === "HIGH" ? "🔴" : "🟡"} ${item.mistake}`;
        list.appendChild(li);
      });
      $("arena-mistakes-wrap").hidden = !score.mistakes?.length;
      $("arena-no-mistakes").hidden = !!score.mistakes?.length;
      const feedbackList = $("arena-feedback");
      feedbackList.replaceChildren();
      (score.feedback || []).forEach((item) => {
        const li = document.createElement("li");
        const change = item.score_delta > 0 ? `+${item.score_delta}` : String(item.score_delta);
        const tactic = item.tactic ? ` · Chiêu: ${item.tactic}` : "";
        li.textContent = `Lượt ${item.turn_no} · ${item.intent} · ${change}${tactic}: ${item.feedback}`;
        feedbackList.appendChild(li);
      });
      $("arena-feedback-wrap").hidden = !score.feedback?.length;
      $("arena-lesson").textContent = score.lesson_summary || "";
      $("arena-lesson").hidden = !score.lesson_summary;
      const redFlags = $("arena-redflags");
      redFlags.replaceChildren();
      (score.red_flags || []).forEach((flag) => {
        const li = document.createElement("li");
        li.textContent = `${flag.title} (${flag.severity}): ${flag.explanation}`;
        redFlags.appendChild(li);
      });
      $("arena-redflags-wrap").hidden = !score.red_flags?.length;
      if (window.ArenaHistory) setTimeout(() => window.ArenaHistory.refreshAll(), 1200);
    } catch (error) {
      $("arena-badge").textContent = `Chưa chấm được: ${error.message}`;
      $("arena-score").textContent = "—";
    }
  }

  sendButton.addEventListener("click", () => {
    const elapsed = lastScammerAt ? Math.max(0, (Date.now() - lastScammerAt) / 1000) : null;
    sendReply(textInput.value, elapsed);
  });
  textInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendButton.click(); }
  });
  micButton.addEventListener("click", toggleRecording);
  $("arena-random-btn").addEventListener("click", async () => {
    try { await startSession(await Api.randomScenario()); }
    catch (error) { $("picker-error").hidden = false; $("picker-error").textContent = error.message; }
  });
  $("arena-finish-btn").addEventListener("click", finishSession);
  $("arena-cancel-btn").addEventListener("click", () => {
    clearInterval(timerHandle);
    if (recording && mediaRecorder?.state !== "inactive") mediaRecorder.stop();
    if (mediaRecorder?.stream) mediaRecorder.stream.getTracks().forEach((track) => track.stop());
    recording = false;
    if (sessionId) Api.finishCall(sessionId).catch(() => {});
    session.hidden = true;
    picker.hidden = false;
    callEnded = true;
  });
  $("arena-restart-btn").addEventListener("click", () => {
    result.hidden = true;
    picker.hidden = false;
  });
  loadScenarios();
})();
