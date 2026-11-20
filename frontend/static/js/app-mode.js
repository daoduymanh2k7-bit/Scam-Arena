(() => {
  const messageScreen = document.getElementById("message-mode");
  const callScreen = document.getElementById("call-static-screen");
  const modeButtons = [...document.querySelectorAll("#mode-nav [data-mode]")];
  if (!messageScreen || !callScreen || !modeButtons.length) return;

  const phone = callScreen.querySelector(".call-device-screen");
  const callControls = [...phone.querySelectorAll("[data-call-controls]")];
  const callStatus = document.getElementById("phone-call-status");
  const callTimer = document.getElementById("phone-call-timer");
  const clock = document.getElementById("phone-clock");
  const callerTitle = document.getElementById("call-static-title");
  const scenarioOptions = document.getElementById("call-scenario-options");
  const scenarioStatus = document.getElementById("call-scenarios-status");
  const subtitlesLog = document.getElementById("call-subtitles-log");
  const subtitlesEmpty = document.getElementById("call-subtitles-empty");
  const micButton = document.getElementById("phone-call-mute");
  const micLabel = document.getElementById("phone-mute-label");
  const audioButton = document.getElementById("phone-call-audio");
  const endButton = phone.querySelector('[data-call-action="end"]');
  const smsBanner = document.getElementById("phone-sms-banner");
  const smsPreview = document.getElementById("phone-sms-preview");
  const smsBody = document.getElementById("phone-sms-body");
  const smsStatus = document.getElementById("phone-sms-status");
  const smsCode = document.getElementById("phone-sms-code");
  let timer = null;
  let startedAt = 0;
  let smsDeliveryTimer = null;
  let loadingScenarios = false;
  let scenariosLoaded = false;
  let selectedScenario = null;
  const phoneAudio = new Audio();
  let cancelPlayback = null;
  let callRun = 0;
  let sessionId = null;
  let introPhase = "greeting";
  let turnBusy = false;
  let microphone = null;
  let micMuted = false;
  let micError = "";
  let lastLineFinishedAt = 0;
  let greetingTimer = null;
  let otpScheduled = false;
  let callerVoices = [];
  let currentVoice = null;
  let previousVoice = null;

  function pickCallerVoice() {
    const otherVoices = callerVoices.filter((voice) => voice !== previousVoice);
    const pool = otherVoices.length ? otherVoices : callerVoices;
    const voice = pool[Math.floor(Math.random() * pool.length)] ?? null;
    previousVoice = voice;
    return voice;
  }

  const lineSources = {
    fixed: "Luật / câu thoại có sẵn",
    llm: "LLM vừa tạo",
    cache_exact: "Câu LLM đã lưu, khớp câu người chơi",
    cache_pool: "Câu LLM lấy từ kho lời thoại",
  };
  const intentNames = {
    verify: "Tự xác minh", refuse: "Từ chối", doubt: "Nghi ngờ", comply: "Đồng ý làm theo",
    share_sensitive: "Chia sẻ dữ liệu nhạy cảm", transfer_money: "Chuyển tiền",
    hang_up: "Muốn kết thúc", unknown: "Chưa nhận diện rõ",
  };
  const intentMethods = { rule: "Luật", rasa: "Rasa", llm: "LLM", fallback: "Dự phòng" };

  function addSubtitleInfo(entry, text) {
    const info = document.createElement("details");
    info.className = "call-subtitle-info";
    const toggle = document.createElement("summary");
    toggle.textContent = "i";
    toggle.setAttribute("aria-label", "Xem thông tin phụ đề");
    const description = document.createElement("div");
    description.textContent = text;
    info.append(toggle, description);
    entry.append(info);
  }

  function addSubtitle(source, text, info = null) {
    const entry = document.createElement("div");
    entry.className = `call-subtitle call-subtitle--${source}`;
    const label = document.createElement("strong");
    const body = document.createElement("p");
    const labels = { caller: "Người gọi", speech: "Máy nghe bạn nói", notice: "Nhận dạng giọng nói" };
    label.textContent = labels[source];
    body.textContent = text;
    entry.append(label, body);
    if (info) addSubtitleInfo(entry, info);
    subtitlesEmpty.hidden = true;
    subtitlesLog.append(entry);
    subtitlesLog.scrollTop = subtitlesLog.scrollHeight;
    return entry;
  }

  function stopAudio() {
    cancelPlayback?.();
    if (!phoneAudio.hasAttribute("src")) return;
    phoneAudio.pause();
    phoneAudio.removeAttribute("src");
    phoneAudio.load();
  }

  function playAudio(source, loop = false) {
    stopAudio();
    phoneAudio.loop = loop;
    phoneAudio.src = source;
    return new Promise((resolve) => {
      const finish = (played) => {
        if (cancelPlayback !== cancel) return;
        cancelPlayback = null;
        phoneAudio.removeEventListener("ended", ended);
        phoneAudio.removeEventListener("error", failed);
        resolve(played);
      };
      const cancel = () => finish(false);
      const ended = () => finish(true);
      const failed = () => finish(false);
      cancelPlayback = cancel;
      phoneAudio.addEventListener("ended", ended);
      phoneAudio.addEventListener("error", failed);
      phoneAudio.play().then(() => { if (loop) finish(true); }, failed);
    });
  }

  async function speakLine(line, run, metadata = {}) {
    if (run !== callRun) return false;
    const source = lineSources[metadata.line_source ?? "fixed"] ?? "Không rõ nguồn";
    const timing = metadata.line_source && metadata.line_source !== "fixed" && Number.isFinite(metadata.line_latency_ms)
      ? ` · ${metadata.line_latency_ms} ms`
      : "";
    addSubtitle("caller", line, `Nguồn: ${source}${timing}`);
    try {
      const wav = await Api.speakText(line, currentVoice);
      if (run !== callRun) return false;
      const url = URL.createObjectURL(wav);
      try {
        return await playAudio(url);
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch {
      return false;
    }
  }

  function setTurnBusy(busy) {
    turnBusy = busy;
    syncMicrophone();
  }

  function listeningStatus() {
    if (micError) return micError;
    if (micMuted) return "Micro đang tắt.";
    return microphone?.ready ? "Đang nghe bạn…" : "Đang mở micro…";
  }

  function waitForReply(status) {
    lastLineFinishedAt = Date.now();
    callStatus.textContent = status || listeningStatus();
    setTurnBusy(false);
  }

  async function answerCall() {
    setCallState("active", "Đang chuẩn bị micro…", true);
    const run = callRun;
    currentVoice = pickCallerVoice();
    const query = currentVoice ? `?voice=${encodeURIComponent(currentVoice)}` : "";
    await openMicrophone(run);
    if (run !== callRun) return;
    callStatus.textContent = "Người gọi đang nói…";
    addSubtitle("caller", "Alo?", "Nguồn: Lời chào có sẵn");
    const played = await playAudio(`/api/voice/greeting${query}`);
    if (run !== callRun) return;
    if (!played) addSubtitle("notice", "Không phát được âm thanh. Lời người gọi vẫn có trong phụ đề.");
    waitForReply();
    greetingTimer = setTimeout(async () => {
      if (run !== callRun || turnBusy || micMuted || !microphone?.ready) return;
      setTurnBusy(true);
      callStatus.textContent = "Người gọi đang nói…";
      const line = "Alo, anh chị còn nghe máy không ạ?";
      const heard = await speakLine(line, run);
      if (run !== callRun) return;
      if (!heard) addSubtitle("notice", "Không phát được âm thanh. Lời người gọi vẫn có trong phụ đề.");
      waitForReply();
    }, 12000);
  }

  async function finishSession(id) {
    try {
      await Api.finishCall(id);
      window.ArenaHistory?.refreshAll();
    } catch {
      // A connection failure should not prevent the local call from closing.
    }
  }

  async function handleReply(text, elapsed, run, recognition = "Whisper") {
    clearTimeout(greetingTimer);
    const subtitle = addSubtitle("speech", text);
    const isIntro = introPhase !== "scenario";
    if (isIntro) addSubtitleInfo(subtitle, `Nhận dạng giọng: ${recognition} · Lượt chào, chưa gán nhãn ý định`);
    setTurnBusy(true);
    callStatus.textContent = "Đang xử lý câu trả lời…";
    try {
      let response;
      if (introPhase !== "scenario") {
        const normalized = text.toLocaleLowerCase("vi").replace(/[.,!?…]+/g, " ").replace(/\s+/g, " ").trim();
        if (/^(?:(?:tôi )?(?:cúp|ngắt|gác) máy|tạm biệt)$/.test(normalized)) {
          setCallState("ended", "Bạn đã kết thúc cuộc gọi.", true);
          return;
        }
        const isGreeting = /^(?:(?:alo|alô|a lô|dạ|vâng|ừ|tôi nghe|em nghe|mình nghe|nghe đây)(?: |$))+$/.test(normalized);
        if (introPhase === "greeting" && isGreeting) {
          introPhase = "courtesy";
          response = { bot_text: "Dạ, anh chị tiện nghe máy một chút không ạ?" };
        } else {
          response = await Api.startCall(selectedScenario, "call");
          if (run !== callRun) {
            void finishSession(response.session_id);
            return;
          }
          sessionId = response.session_id;
          introPhase = "scenario";
          // The caller already greeted the player before this stored opening.
          response.bot_text = response.bot_text.replace(/^(?:alo|alô|a lô)(?=[\s,.!?…:]|$)[\s,.!?…:]*/iu, "");
        }
      } else {
        response = await Api.submitCallTurn(sessionId, text, elapsed);
        if (run !== callRun) return;
        const intent = intentNames[response.intent] ?? "Chưa xác định";
        const method = intentMethods[response.intent_method] ?? "Không rõ";
        addSubtitleInfo(subtitle, `Nhận dạng giọng: ${recognition} · Ý định: ${intent} · Cách gán nhãn: ${method}`);
        if (response.ended) {
          sessionId = null;
          window.ArenaHistory?.refreshAll();
        }
      }

      const line = response.bot_text;
      callStatus.textContent = "Người gọi đang nói…";
      const heard = line ? await speakLine(line, run, response) : true;
      if (run !== callRun) return;
      if (response.ended) {
        const score = Number.isFinite(response.score) ? ` · ${response.score}/100` : "";
        setCallState("ended", `Cuộc gọi đã kết thúc${score}.`, true);
        return;
      }
      if (selectedScenario === "bank" && response.stage === "ask_action" && !otpScheduled) {
        otpScheduled = true;
        smsDeliveryTimer = setTimeout(deliverDemoSms, 300);
      }
      if (!heard) addSubtitle("notice", "Không phát được âm thanh. Lời người gọi vẫn có trong phụ đề.");
      waitForReply();
    } catch (error) {
      if (run === callRun) {
        if (!isIntro && !subtitle.querySelector("details")) {
          addSubtitleInfo(subtitle, `Nhận dạng giọng: ${recognition} · Chưa có kết quả gán nhãn ý định`);
        }
        waitForReply(`Chưa xử lý được câu trả lời: ${error.message}`);
      }
    }
  }

  function responseDelay() {
    return Math.min(3600, Math.max(0, (Date.now() - lastLineFinishedAt) / 1000));
  }

  function syncMicrophone() {
    if (!microphone?.ready) return;
    void microphone.setEnabled(!turnBusy && !micMuted);
  }

  function releaseMicrophone() {
    const mic = microphone;
    microphone = null;
    void mic?.destroy().catch(() => {});
  }

  function updateMicButton() {
    micButton.setAttribute("aria-pressed", String(micMuted));
    micLabel.textContent = micError ? "Thử lại micro" : micMuted ? "Bật micro" : "Tắt micro";
  }

  function samplesToWav(samples, rate) {
    const dataLength = samples.length * 2;
    const buffer = new ArrayBuffer(44 + dataLength);
    const view = new DataView(buffer);
    function writeTag(offset, tag) {
      for (let index = 0; index < tag.length; index++) view.setUint8(offset + index, tag.charCodeAt(index));
    }
    writeTag(0, "RIFF");
    view.setUint32(4, 36 + dataLength, true);
    writeTag(8, "WAVE");
    writeTag(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeTag(36, "data");
    view.setUint32(40, dataLength, true);
    for (let index = 0; index < samples.length; index++) {
      const value = Math.max(-1, Math.min(1, samples[index]));
      view.setInt16(44 + index * 2, Math.round(value * 32767), true);
    }
    return new Blob([buffer], { type: "audio/wav" });
  }

  async function recognizeSpeech(data, elapsed, run) {
    setTurnBusy(true);
    callStatus.textContent = "Đang nhận diện lời nói…";
    try {
      const result = await Api.transcribeAudio(samplesToWav(data.samples, data.rate));
      if (run !== callRun) return;
      const text = result.text.trim();
      if (!text) throw new Error("Chưa nghe rõ câu vừa rồi.");
      const recognition = [data.capture_method, result.engine || "Whisper", result.model,
        typeof result.compute_type === "string" ? result.compute_type.toUpperCase() : null,
        Number.isFinite(result.elapsed_ms) ? `${result.elapsed_ms} ms` : null].filter(Boolean).join(" · ");
      await handleReply(text, elapsed, run, recognition);
    } catch (error) {
      if (run !== callRun) return;
      addSubtitle("notice", error.message);
      waitForReply("Chưa nghe rõ. Bạn có thể nói lại.");
    }
  }

  async function openMicrophone(run) {
    if (microphone) return;
    micError = "";
    updateMicButton();
    if (!turnBusy) callStatus.textContent = listeningStatus();
    try {
      if (!navigator.mediaDevices?.getUserMedia || !(window.AudioContext || window.webkitAudioContext) || !window.CallMicrophone) {
        throw new Error("unsupported");
      }
      const current = () => mic === microphone && run === callRun;
      const mic = new CallMicrophone.Capture({
        onSpeechStart: () => {
          if (!current() || turnBusy || micMuted) return;
          clearTimeout(greetingTimer);
          mic.elapsed = responseDelay();
          callStatus.textContent = "Đang nghe bạn nói…";
        },
        onSpeech: (data) => {
          if (current() && !turnBusy && !micMuted) void recognizeSpeech(data, mic.elapsed, run);
        },
        onMisfire: () => { if (current() && !turnBusy) callStatus.textContent = listeningStatus(); },
        onFallback: () => {
          if (current()) addSubtitle("notice", "Bộ bắt giọng Silero chưa mở được; đang dùng bộ bắt giọng dự phòng.");
        },
        onError: () => {
          if (!current()) return;
          releaseMicrophone();
          micError = "Micro gặp lỗi xử lý. Bấm Thử lại micro để kết nối lại.";
          updateMicButton();
          if (!turnBusy) callStatus.textContent = micError;
        },
      });
      microphone = mic;
      await mic.initialize();
      if (!current()) { void mic.destroy().catch(() => {}); return; }
      syncMicrophone();
      if (!turnBusy && !micMuted) waitForReply();
    } catch (error) {
      if (run !== callRun) return;
      releaseMicrophone();
      micError = error.message === "unsupported"
        ? "Micro cần trình duyệt hỗ trợ và trang HTTPS hoặc localhost."
        : error.name === "NotAllowedError"
          ? "Hãy cấp quyền micro rồi bấm Thử lại micro."
          : "Chưa mở được micro. Kiểm tra thiết bị rồi thử lại.";
      updateMicButton();
      if (!turnBusy) callStatus.textContent = micError;
    }
  }

  function toggleMicrophone() {
    if (micError) {
      void openMicrophone(callRun);
      return;
    }
    micMuted = !micMuted;
    updateMicButton();
    syncMicrophone();
    if (!turnBusy) callStatus.textContent = listeningStatus();
  }

  function resetCall() {
    selectedScenario = null;
    setCallState("idle", "Chọn tình huống để bắt đầu");
  }

  async function loadCallScenarios() {
    if (loadingScenarios || scenariosLoaded) return;
    loadingScenarios = true;
    scenarioStatus.textContent = "Đang tải tình huống…";
    try {
      const [scenarios, voices] = await Promise.all([
        Api.listScenarios(),
        Api.listCallerVoices().catch(() => []),
      ]);
      callerVoices = Array.isArray(voices) ? voices : [];
      scenarioOptions.replaceChildren(...scenarios.map((scenario) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = scenario.label;
        button.addEventListener("click", () => {
          selectedScenario = scenario.key;
          clock.textContent = new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
          setCallState("ringing", "Cuộc gọi đến", true);
        });
        return button;
      }));
      scenariosLoaded = true;
      scenarioStatus.textContent = scenarios.length ? "" : "Chưa có tình huống";
    } catch {
      scenarioStatus.textContent = "Không tải được tình huống. Hãy mở lại tab Cuộc gọi.";
    } finally {
      loadingScenarios = false;
    }
  }

  function updateDuration() {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
    callTimer.textContent = `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
  }

  function deliverDemoSms() {
    smsCode.textContent = String(Math.floor(Math.random() * 1000000)).padStart(6, "0");
    smsStatus.textContent = "Có tin nhắn mới từ Ngân hàng mô phỏng.";
    smsBanner.hidden = false;
  }

  function resetSms() {
    clearTimeout(smsDeliveryTimer);
    smsBanner.hidden = true;
    setSmsExpanded(false);
    smsStatus.textContent = "";
    smsCode.textContent = "";
  }

  function setSmsExpanded(expanded) {
    smsBody.hidden = !expanded;
    smsPreview.setAttribute("aria-expanded", String(expanded));
  }

  function setCallState(state, label, moveFocus = false) {
    const run = ++callRun;
    clearInterval(timer);
    clearTimeout(greetingTimer);
    timer = null;
    stopAudio();
    resetSms();
    otpScheduled = false;
    releaseMicrophone();
    micMuted = false;
    micError = "";
    updateMicButton();
    phoneAudio.muted = false;
    audioButton.setAttribute("aria-pressed", "false");
    if (sessionId) {
      void finishSession(sessionId);
      sessionId = null;
    }
    introPhase = "greeting";
    setTurnBusy(state === "active");
    phone.dataset.callState = state;
    callerTitle.textContent = state === "idle" ? "Điện thoại" : "Số không xác định";
    callStatus.textContent = label;
    callTimer.hidden = state !== "active";
    for (const controls of callControls) {
      controls.hidden = controls.dataset.callControls !== state;
      if (!controls.hidden && moveFocus) controls.querySelector("button:not(:disabled)").focus({ preventScroll: true });
    }
    if (state === "ringing") {
      subtitlesEmpty.hidden = false;
      subtitlesLog.replaceChildren(subtitlesEmpty);
      playAudio("/audio/call-ringtone.wav", true).then((played) => {
        if (!played && run === callRun) callStatus.textContent = "Cuộc gọi đến · Không phát được nhạc chuông.";
      });
    }
    if (state === "active") {
      startedAt = Date.now();
      updateDuration();
      timer = setInterval(updateDuration, 1000);
    }
  }

  phone.addEventListener("click", (event) => {
    const action = event.target.closest("[data-call-action]")?.dataset.callAction;
    switch (action) {
      case "accept":
        void answerCall();
        break;
      case "mute-mic": toggleMicrophone(); break;
      case "mute-audio":
        phoneAudio.muted = !phoneAudio.muted;
        audioButton.setAttribute("aria-pressed", String(phoneAudio.muted));
        break;
      case "decline": setCallState("ended", "Đã từ chối cuộc gọi", true); break;
      case "end": setCallState("ended", "Cuộc gọi đã kết thúc", true); break;
      case "reset": setCallState("ringing", "Cuộc gọi đến", true); break;
      case "choose":
        resetCall();
        scenarioOptions.querySelector("button")?.focus({ preventScroll: true });
        break;
      case "expand-sms":
        setSmsExpanded(smsBody.hidden);
        break;
      case "close-sms":
        smsBanner.hidden = true;
        setSmsExpanded(false);
        endButton.focus({ preventScroll: true });
        break;
    }
  });

  function showMode(mode) {
    const isCall = mode === "call";
    const enteringCall = isCall && callScreen.hidden;
    messageScreen.hidden = isCall;
    callScreen.hidden = !isCall;
    if (!isCall) resetCall();
    if (enteringCall) {
      loadCallScenarios();
      void CallMicrophone.preload().catch(() => {});
    }
    modeButtons.forEach((button) => {
      const active = button.dataset.mode === mode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => showMode(button.dataset.mode));
  });

  showMode("message");
})();
