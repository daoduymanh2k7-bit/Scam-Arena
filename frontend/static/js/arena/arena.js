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
    sendButton.disabled = value || callEnded || !textInput.value.trim();
    transcriptBox.setAttribute("aria-busy", String(value));
    $("arena-typing").hidden = !value;
    textInput.disabled = value || callEnded;
    micButton.disabled = value || callEnded;
  }
  const intentNames = {
    verify: "Muốn tự xác minh", refuse: "Từ chối", hang_up: "Muốn kết thúc cuộc gọi",
    doubt: "Nghi ngờ", comply: "Đồng ý làm theo", share_sensitive: "Chia sẻ thông tin nhạy cảm",
    transfer_money: "Đồng ý chuyển tiền", unknown: "Chưa nhận diện rõ",
  };
  const intentMethods = { rule: "luật an toàn", rasa: "bộ nhận diện Rasa", llm: "LLM", fallback: "dự phòng" };
  const lineSources = {
    cache_exact: "LLM (dùng lại câu khớp chính xác từ bộ nhớ)",
    cache_pool: "LLM (dùng lại câu trong bộ nhớ)", llm: "LLM (vừa tạo câu này)", fixed: "luật/kịch bản cố định",
  };
  function addBubble(text, role, metadata = null) {
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role === "user" ? "user" : "scammer"}`;
    const content = document.createElement("div");
    content.className = "bubble-text";
    content.textContent = text;
    bubble.appendChild(content);
    const footer = document.createElement("div");
    footer.className = "message-bubble-footer";
    const time = document.createElement("time");
    time.dateTime = new Date().toISOString();
    time.textContent = new Date().toLocaleTimeString("vi-VN", {hour:"2-digit",minute:"2-digit"});
    footer.append(time);
    if (metadata?.intent || metadata?.line_source) {
      const info = document.createElement("details");
      info.className = "message-bubble-info";
      const toggle = document.createElement("summary");
      toggle.textContent = "i";
      toggle.setAttribute("aria-label", "Xem nguồn và thông tin nhận diện tin nhắn");
      const detail = document.createElement("div");
      if (metadata.intent) detail.textContent = `Nhận diện: ${intentNames[metadata.intent] || metadata.intent} · ${intentMethods[metadata.intent_method] || metadata.intent_method}`;
      else detail.textContent = `Nguồn: ${lineSources[metadata.line_source] || metadata.line_source} · ${metadata.line_latency_ms ?? 0} ms`;
      info.append(toggle, detail);
      footer.append(info);
    }
    bubble.append(footer);
    if (role !== "user" && metadata?.turn_no != null) {
      const options = document.createElement("details");
      options.className = "bubble-options";
      const summary = document.createElement("summary");
      summary.textContent = "Tùy chọn trả lời";
      const actions = document.createElement("div");
      actions.className = "bubble-actions";
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "bubble-action";
      retry.textContent = "Trả lời lại câu này";
      retry.addEventListener("click", async () => {
        retry.disabled = true;
        retry.textContent = "Đang tạo câu mới…";
        try {
          const alternative = await Api.regenerateLine(sessionId, metadata.turn_no, metadata.line_id);
          addBubble(alternative.bot_text, "scammer", { line_source: alternative.line_source,
            line_latency_ms: alternative.line_latency_ms, line_id: alternative.line_id, turn_no: alternative.turn_no });
          setStatus("Đã thêm câu trả lời mới; câu cũ vẫn được giữ lại.");
          await speak(alternative.bot_text);
          setStatus("Đến lượt bạn. Hãy bình tĩnh trả lời hoặc yêu cầu xác minh.");
        } catch (error) {
          setStatus(`Chưa tạo được câu trả lời mới: ${error.message}`);
          retry.disabled = false;
          retry.textContent = "Trả lời lại câu này";
        }
      });
      actions.appendChild(retry);
      if (metadata.line_id != null) {
        const like = document.createElement("button");
        like.type = "button";
        like.className = "bubble-action";
        like.textContent = "♡ Thích câu này";
        like.addEventListener("click", async () => {
          like.disabled = true;
          try {
            await Api.likeLine(sessionId, metadata.turn_no, metadata.line_id);
            like.textContent = "♥ Đã thích";
          } catch (error) {
            like.disabled = false;
            setStatus(`Chưa ghi nhận được lượt thích: ${error.message}`);
          }
        });
        actions.appendChild(like);
      }
      options.append(summary, actions);
      bubble.appendChild(options);
    }
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
    $("arena-typing").hidden = true;
    addBubble(line, "scammer", { line_source: response.line_source || "fixed", line_latency_ms: response.line_latency_ms ?? 0,
      line_id: response.line_id, turn_no: response.turn_no });
    updateCallState(response);
    setStatus("Đang phát giọng đọc…");
    await speak(line);
    if (!callEnded && response.intent === "unknown") {
      setStatus("Bạn có thể diễn đạt rõ hơn để tiếp tục trò chuyện.");
    } else if (callEnded) {
      setStatus("Cuộc trò chuyện đã kết thúc. Chọn xem điểm để đọc nhận xét.");
    } else if (!callEnded) {
      setStatus("Đến lượt bạn. Hãy trả lời theo cách bạn sẽ làm ngoài đời.");
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
    resizeInput();
    setBusy(true);
    setCallTimer();
    setStatus("Đang mở cuộc trò chuyện…");
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
    setStatus("Đang gửi tin nhắn…");
    try {
      const response = await Api.submitCallTurn(sessionId, answer, elapsed);
      addBubble(answer, "user", { intent: response.intent, intent_method: response.intent_method });
      textInput.value = "";
      resizeInput();
      await showScammer(response);
    } catch (error) {
      setStatus(`Chưa gửi được câu trả lời: ${error.message}`);
    } finally { setBusy(false); }
  }
  async function loadScenarios() {
    try {
      const scenarios = await Api.listScenarios();
      scenarios.filter(item=>!item.key.startsWith('mixed-')).forEach((item) => {
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

  function resizeInput() {
    textInput.style.height = 'auto';
    textInput.style.height = Math.min(textInput.scrollHeight,112) + 'px';
  }
  textInput.addEventListener('input', () => {
    resizeInput();
    sendButton.disabled = busy || callEnded || !textInput.value.trim();
  });
  sendButton.addEventListener("click", () => {
    const elapsed = lastScammerAt ? Math.max(0, (Date.now() - lastScammerAt) / 1000) : null;
    sendReply(textInput.value, elapsed);
  });
  textInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendButton.click(); }
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
