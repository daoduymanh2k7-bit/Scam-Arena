(() => {
  const $ = (id) => document.getElementById(id);
  const picker = $("arena-picker"), session = $("arena-session"), result = $("arena-result");
  const scenarioList = $("arena-scenario-list"), transcriptBox = $("arena-transcript");
  const textInput = $("arena-text-input"), micButton = $("arena-mic-btn");
  const sendButton = $("arena-send-btn"), status = $("arena-status");
  const audioPlayer = $("arena-audio-player");
  let scenario = null, history = [], sessionId = null, mediaRecorder = null, chunks = [];
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
  function detectCallEnd(line) {
    if (line.includes("kết thúc cuộc gọi") || line.includes("kịch bản demo đã kết thúc")) {
      callEnded = true;
      micButton.disabled = true;
      sendButton.disabled = true;
      textInput.disabled = true;
    }
  }
  async function showScammer(line) {
    history.push({ role: "scammer_ai", text: line, elapsed_seconds: null });
    addBubble(line, "scammer");
    detectCallEnd(line);
    setStatus("Đang phát lời thoại…");
    await speak(line);
    if (!callEnded) setStatus("Đến lượt bạn. Hãy bình tĩnh trả lời hoặc yêu cầu xác minh.");
  }
  async function startSession(nextScenario) {
    scenario = nextScenario;
    history = [];
    sessionId = crypto.randomUUID();
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
      const { reply } = await Api.scammerReply(scenario.key, history, "");
      await showScammer(reply);
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
      const { reply } = await Api.scammerReply(scenario.key, history, answer);
      history.push({ role: "user", text: answer, elapsed_seconds: elapsed });
      addBubble(answer, "user");
      textInput.value = "";
      await showScammer(reply);
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
      const score = await Api.scoreSession(sessionId, scenario.label, history);
      $("arena-score").textContent = String(score.user_score);
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
