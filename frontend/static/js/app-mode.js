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
  const randomStart = document.getElementById('call-random-start');
  const scenarioToggle = document.getElementById('call-scenario-toggle');
  const scenarioMenu = document.getElementById('call-scenario-menu');
  const scenarioStatus = document.getElementById("call-scenarios-status");
  const subtitlesPanel = callScreen.querySelector(".call-subtitles");
  const subtitlesLog = document.getElementById("call-subtitles-log");
  const subtitlesEmpty = document.getElementById("call-subtitles-empty");
  const micButton = document.getElementById("phone-call-mute");
  const micLabel = document.getElementById("phone-mute-label");
  const audioButton = document.getElementById("phone-call-audio");
  const endButton = phone.querySelector('[data-call-action="end"]');
  const inbox = new PhoneInbox(phone);
  let timer = null;
  let startedAt = 0;
  let loadingScenarios = false;
  let scenariosLoaded = false;
  let selectedScenario = null;
  const phoneAudio = new Audio();
  let cancelPlayback = null;
  let callRun = 0;
  let sessionId = null;
  let latestCallTurn = null;
  let mixedSession = null;
  let preparedStart = null;
  const practicePanel = document.createElement('div');
  practicePanel.className='practice-call-panel';
  practicePanel.hidden = true;
  practicePanel.innerHTML = `<p data-context>Bạn sẽ nhận một cuộc gọi dịch vụ chưa rõ thật/giả. Bối cảnh cụ thể xuất hiện khi cuộc gọi bắt đầu.</p>
    <label>Độ khó <select data-difficulty><option value="adaptive">Theo kết quả luyện tập</option><option value="beginner">Cơ bản</option><option value="intermediate">Trung bình</option><option value="advanced">Nâng cao</option></select></label>
    <label>Chế độ <select data-exercise><option value="training">Luyện tập</option><option value="assessment">Đánh giá (không tạo lại câu)</option></select></label>
    <p>Công cụ trong điện thoại:</p><button type="button" data-event="check_context">Xem hồ sơ / đơn / lịch</button>
    <button type="button" data-event="read_message">Đọc thông báo</button><button type="button" data-event="verify_official">Tự kiểm tra kênh chính thức</button>
    <button type="button" data-event="open_requested_link" hidden>Mở liên kết mô phỏng</button><button type="button" data-event="share_demo_code" hidden>Gửi mã mô phỏng</button>
    <p data-evidence-text></p><button type="button" data-finish-retry hidden>Lưu kết thúc lại</button><p>Nhận định sau cuộc gọi:</p><textarea data-reason rows="2" maxlength="1000" placeholder="Bạn dựa vào dấu hiệu nào? (không nhập dữ liệu thật)"></textarea>
    <button type="button" data-judge="benign">Bình thường</button> <button type="button" data-judge="fraud">Giả mạo</button> <button type="button" data-judge="uncertain">Chưa đủ thông tin</button><p data-result></p>`;
  scenarioMenu.after(practicePanel);
  const isMixed = () => selectedScenario?.startsWith('mixed-');
  const isAssessment = () => isMixed() && practicePanel.querySelector('[data-exercise]').value === 'assessment';
  async function refreshPractice() {
    if (!mixedSession) return;
    const owner=mixedSession;
    const response=await fetch(`/api/practice/${owner}/context`);
    if (!response.ok || mixedSession!==owner) return;
    const state=await response.json();
    practicePanel.querySelector('[data-context]').textContent=state.context;
    practicePanel.querySelectorAll('[data-event]').forEach(button=>{
      button.hidden=!state.actions.includes(button.dataset.event);
      button.disabled=state.ended;
    });
  }
  practicePanel.addEventListener('click', async event => {
    const button=event.target.closest('button');
    if (!button || !mixedSession) return;
    const owner=mixedSession;
    button.disabled=true;
    try {
      if (button.hasAttribute('data-finish-retry')) {
        if (!await finishSession(owner)) throw Error('Chưa lưu được kết thúc. Hãy thử lại.');
        if(mixedSession!==owner)return;
        button.hidden=true;practicePanel.querySelectorAll('[data-judge]').forEach(b=>b.disabled=false);return;
      }
      const evidence=Boolean(button.dataset.event);
      const response=await fetch(`/api/practice/${encodeURIComponent(owner)}/${evidence?'events':'judge'}`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(evidence?{event_type:button.dataset.event}:{judgement:button.dataset.judge,reason:practicePanel.querySelector('[data-reason]').value})});
      const data=await response.json();
      if (mixedSession!==owner) return;
      if (!response.ok) throw Error(data.detail||'Chưa thực hiện được.');
      if (evidence) {
        practicePanel.querySelector('[data-evidence-text]').textContent=data.text;
        if (button.dataset.event==='read_message') {
          await inbox.refresh();if(mixedSession===owner)inbox.showList();
        }
      } else {
        practicePanel.querySelector('[data-result]').textContent=`Cuộc gọi ${data.actual_kind==='benign'?'bình thường':'giả mạo'}. ${data.correct?'Nhận định đúng.':data.judgement==='uncertain'?'Bạn chưa kết luận.':'Nhận định chưa đúng.'} Điểm đánh giá: ${data.evaluation_score}/100. ${data.verified_independently?'Đã kiểm tra kênh độc lập.':''} ${data.risk_action_recorded?'Có thao tác mô phỏng rủi ro.':''} ${data.explanation} ${data.note}`;
        practicePanel.querySelectorAll('[data-judge]').forEach(b=>b.disabled=true);
      }
    } catch(error) {if(mixedSession===owner){practicePanel.querySelector('[data-result]').textContent=error.message;button.disabled=false;}}
  });
  let introPhase = "greeting";
  let turnBusy = false;
  let microphone = null;
  let partialSpeech = null;
  let streamingSpeech = null;
  let partialEntry = null;
  let micMuted = false;
  let micError = "";
  let lastLineFinishedAt = 0;
  let greetingTimer = null;
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
    if (isAssessment()) return;
    const existing = entry.querySelector(".call-subtitle-info div");
    if (existing) { existing.textContent += ` · ${text}`; return; }
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

  function playAudio(source, loop = false, onStarted = null) {
    stopAudio();
    phoneAudio.loop = loop;
    phoneAudio.src = source;
    return new Promise((resolve) => {
      const finish = (played) => {
        if (cancelPlayback !== cancel) return;
        cancelPlayback = null;
        phoneAudio.removeEventListener("ended", ended);
        phoneAudio.removeEventListener("error", failed);
        phoneAudio.removeEventListener("playing", playing);
        resolve(played);
      };
      const cancel = () => finish(false);
      const ended = () => finish(true);
      const failed = () => finish(false);
      const playing = () => { onStarted?.(); };
      cancelPlayback = cancel;
      phoneAudio.addEventListener("ended", ended);
      phoneAudio.addEventListener("error", failed);
      phoneAudio.addEventListener("playing", playing, { once: true });
      phoneAudio.play().then(() => { if (loop) finish(true); }, failed);
    });
  }

  function updateRetryButtons() {
    subtitlesLog.querySelectorAll(".call-retry-reply").forEach(button => {
      button.disabled = turnBusy || !sessionId || Number(button.dataset.turn) !== latestCallTurn;
    });
  }

  function addReplyRetry(entry, metadata, run) {
    if (!Number.isInteger(metadata.turn_no) || metadata.ended || isAssessment()) return;
    const ownerSession = sessionId;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "call-retry-reply";
    button.dataset.turn = metadata.turn_no;
    button.textContent = "Tạo câu trả lời khác";
    button.title = "Dùng lại câu bạn vừa nói; giữ nguyên điểm và nhánh kịch bản.";
    button.addEventListener("click", async () => {
      if (turnBusy || run !== callRun || sessionId !== ownerSession || latestCallTurn !== metadata.turn_no) return;
      clearTimeout(greetingTimer);
      streamingSpeech?.cancel();
      setTurnBusy(true);
      stopAudio();
      button.textContent = "Đang tạo câu mới…";
      callStatus.textContent = "Đang tạo câu trả lời khác…";
      try {
        const alternative = await Api.regenerateLine(ownerSession, metadata.turn_no,
          metadata.line_source === "fixed" ? null : metadata.line_id);
        if (run !== callRun || sessionId !== ownerSession) return;
        const heard = await speakLine(alternative.bot_text, run, alternative, null, null, entry);
        if (!heard && run === callRun) addSubtitle("notice", "Không phát được âm thanh. Câu mới đã có trong phụ đề.");
      } catch (error) {
        if (run === callRun) addSubtitle("notice", `Chưa tạo được câu mới: ${error.message}`);
      } finally {
        if (run === callRun) {
          button.textContent = "Tạo câu trả lời khác";
          waitForReply();
        }
      }
    });
    entry.append(button);
    updateRetryButtons();
  }

  async function speakLine(line, run, metadata = {}, latency = null, onStarted = null, replacement = null) {
    if (run !== callRun) return false;
    const source = lineSources[metadata.line_source ?? "fixed"] ?? "Không rõ nguồn";
    const timing = metadata.line_source && metadata.line_source !== "fixed" && Number.isFinite(metadata.line_latency_ms)
      ? ` · ${metadata.line_latency_ms} ms`
      : "";
    const entry = replacement || addSubtitle("caller", line);
    entry.querySelector("p").textContent = line;
    entry.querySelectorAll(".call-subtitle-info, .call-retry-reply").forEach(item => item.remove());
    addSubtitleInfo(entry, `Nguồn: ${source}${timing}`);
    addReplyRetry(entry, metadata, run);
    try {
      const request = () => Api.speakText(line, currentVoice, latency);
      const wav = latency ? await latency.measure("tts_ms", request) : await request();
      if (run !== callRun) return false;
      const url = URL.createObjectURL(wav);
      try {
        latency?.beginPlayback();
        return await playAudio(url, false, () => {
          if (run !== callRun) return;
          latency?.audioStarted();
          onStarted?.();
        });
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch {
      return false;
    }
  }

  function setTurnBusy(busy) {
    turnBusy = busy;
    updateRetryButtons();
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
    const micReady=openMicrophone(run);
    if (isMixed()) {
      try {
        const result=await Api.startCall(selectedScenario,'call',practicePanel.querySelector('[data-difficulty]').value,practicePanel.querySelector('[data-exercise]').value);
        if (run!==callRun) {void finishSession(result.session_id);return;}
        preparedStart=result;mixedSession=result.session_id;void inbox.bind(result.session_id);
        if(result.practice_context)practicePanel.querySelector('[data-context]').textContent=result.practice_context;
        void refreshPractice();
      } catch(error) {if(run===callRun)setCallState('ended',error.message,true);return;}
    }
    await micReady;
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
      return true;
    } catch {
      // A connection failure should not prevent the local call from closing.
      return false;
    }
  }

  async function handleReply(text, elapsed, run, recognition = "Whisper", latency = null, draft = null) {
    clearTimeout(greetingTimer);
    const subtitle = draft || addSubtitle("speech", text);
    if (draft) {
      draft.classList.remove("call-subtitle--partial");
      draft.querySelector("strong").textContent = "Máy nghe bạn nói";
      draft.querySelector("p").textContent = text;
    }
    const isIntro = introPhase !== "scenario";
    if (isIntro) addSubtitleInfo(subtitle, `Nhận dạng giọng: ${recognition} · Lượt chào, chưa gán nhãn ý định`);
    setTurnBusy(true);
    callStatus.textContent = "Đang xử lý câu trả lời…";
    try {
      const replyStarted = performance.now();
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
          response = preparedStart || await Api.startCall(selectedScenario, "call",practicePanel.querySelector("[data-difficulty]").value,isMixed()?practicePanel.querySelector("[data-exercise]").value:'training');
          preparedStart = null;
          if (run !== callRun) {
            void finishSession(response.session_id);
            return;
          }
          sessionId = response.session_id;
          void inbox.bind(sessionId);
          if (isMixed()) {
            mixedSession=sessionId;
            void refreshPractice();
          }
          introPhase = "scenario";
          // The caller already greeted the player before this stored opening.
          response.bot_text = response.bot_text.replace(/^(?:alo|alô|a lô)(?=[\s,.!?…:]|$)[\s,.!?…:]*/iu, "");
        }
      } else {
        response = await Api.submitCallTurn(sessionId, text, elapsed);
        if (run !== callRun) return;
        latestCallTurn = response.turn_no;
        void inbox.refresh();
        if (isMixed()) void refreshPractice();
        const intent = intentNames[response.intent] ?? "Chưa xác định";
        const method = intentMethods[response.intent_method] ?? "Không rõ";
        addSubtitleInfo(subtitle, `Nhận dạng giọng: ${recognition} · Ý định: ${intent} · Cách gán nhãn: ${method}`);
        if (response.ended) {
          sessionId = null;
          window.ArenaHistory?.refreshAll();
        }
      }

      const line = response.bot_text;
      if (latency) latency.reply_ms = performance.now() - replyStarted;
      callStatus.textContent = "Người gọi đang nói…";
      const heard = line ? await speakLine(line, run, response, latency, () => {
        if (latency) addSubtitleInfo(subtitle, latency.description());
      }) : true;
      if (run !== callRun) return;
      if (response.ended) {
        const score = !isMixed() && Number.isFinite(response.score) ? ` · ${response.score}/100` : "";
        setCallState("ended", `Cuộc gọi đã kết thúc${score}.`, true);
        return;
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
    if (turnBusy || micMuted) clearPartial();
    if (micMuted) streamingSpeech?.cancel();
  }

  function clearPartial() {
    partialSpeech?.stop();
    partialEntry?.remove();
    partialEntry = null;
  }

  function releaseMicrophone() {
    streamingSpeech?.cancel();
    streamingSpeech = null;
    clearPartial();
    partialSpeech = null;
    subtitlesLog.querySelectorAll(".call-subtitle--partial").forEach(entry => entry.remove());
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

  async function recognizeSpeech(data, elapsed, run, draft = null, streamResult = null) {
    setTurnBusy(true);
    callStatus.textContent = "Đang nhận diện lời nói…";
    try {
      const latency = new CallLatency(data);
      let result;
      if (streamResult) {
        latency.encode_ms = 0;
        result = await latency.measure("stt_ms", () => streamResult);
      }
      if (!result) {
        if (run !== callRun) return;
        const alreadyWaited = latency.stt_ms || 0;
        const audio = await latency.measure("encode_ms", () => samplesToWav(data.samples, data.rate));
        result = await latency.measure("stt_ms", () => Api.transcribeAudio(audio));
        latency.stt_ms += alreadyWaited;
        if (streamResult || data.stream_fallback) result.transport = "rest_fallback";
      }
      latency.stt_server_ms = result.elapsed_ms;
      latency.transport = result.transport;
      if (run !== callRun) return;
      const text = result.text.trim();
      if (!text) throw new Error("Chưa nghe rõ câu vừa rồi.");
      const recognition = [data.capture_method, result.engine || "Whisper", result.model,
        result.transport === "websocket" ? "Streaming" : result.transport === "rest_fallback" ? "REST dự phòng" : null,
        typeof result.compute_type === "string" ? result.compute_type.toUpperCase() : null,
        Number.isFinite(result.elapsed_ms) ? `${result.elapsed_ms} ms` : null,
        result.beam_size > 0 ? `beam ${result.beam_size}` : null].filter(Boolean).join(" · ");
      await handleReply(text, elapsed, run, recognition, latency, draft);
    } catch (error) {
      if (run !== callRun) return;
      draft?.remove();
      addSubtitle("notice", error.message);
      waitForReply("Chưa nghe rõ. Bạn có thể nói lại.");
    }
  }

  async function openMicrophone(run) {
    if (microphone) return;
    let pendingContext = null;
    micError = "";
    updateMicButton();
    if (!turnBusy) callStatus.textContent = listeningStatus();
    try {
      if (!navigator.mediaDevices?.getUserMedia || !(window.AudioContext || window.webkitAudioContext) || !window.CallMicrophone) {
        throw new Error("unsupported");
      }
      // Resume under the answer-button gesture before awaiting network config.
      pendingContext = new (window.AudioContext || window.webkitAudioContext)();
      pendingContext.resume().catch(() => {});
      const current = () => mic === microphone && run === callRun;
      const streamingConfig = await fetch("/api/voice/stt-status").then(r => r.ok ? r.json() : {}).catch(() => ({}));
      if (run !== callRun) { void pendingContext.close(); return; }
      const stream = streamingConfig.streaming_enabled && streamingConfig.key_configured && window.CallStream
        ? new CallStream(text => {
          if (!current() || turnBusy || micMuted || !partialEntry) return;
          partialEntry.querySelector("p").textContent = text;
          subtitlesLog.scrollTop = subtitlesLog.scrollHeight;
        }) : null;
      streamingSpeech = stream;
      const preview = new PartialSpeech(
        (data, signal) => Api.transcribePartial(samplesToWav(data.samples, data.rate), signal),
        (text) => {
          if (!current() || turnBusy || micMuted || !partialEntry) return;
          partialEntry.querySelector("p").textContent = text;
          subtitlesLog.scrollTop = subtitlesLog.scrollHeight;
        },
        () => {
          if (current()) addSubtitle("notice", "Chữ tạm chưa khả dụng. Hệ thống vẫn nhận diện cả câu khi bạn dừng nói.");
        },
      );
      partialSpeech = preview;
      const mic = new CallMicrophone.Capture({
        onSpeechStart: () => {
          if (!current() || turnBusy || micMuted) return;
          clearTimeout(greetingTimer);
          mic.elapsed = responseDelay();
          callStatus.textContent = "Đang nghe bạn nói…";
          clearPartial();
          if (stream && !stream.failed && mic.method === "Silero VAD v5") stream.start();
          else if (!streamingConfig.streaming_enabled) preview.start();
          partialEntry = addSubtitle("speech", "Đang nghe…");
          partialEntry.classList.add("call-subtitle--partial");
          partialEntry.querySelector("strong").textContent = "Máy đang nghe · Chữ tạm";
        },
        onPartialAudio: (data) => {
          if (!stream && current() && !turnBusy && !micMuted) void preview.offer(data);
        },
        wantsPartial: () => !stream && preview.canOffer(),
        onStreamAudio: samples => {
          if (current() && !turnBusy && !micMuted) stream?.offer(samples);
        },
        onSpeech: (data) => {
          if (!current() || turnBusy || micMuted) return;
          preview.stop();
          const draft = partialEntry;
          partialEntry = null;
          if (draft) draft.querySelector("strong").textContent = "Đang chốt câu…";
          const streamResult = stream?.session ? stream.finish().catch(() => null) : null;
          data.stream_fallback = Boolean(stream?.failed);
          void recognizeSpeech(data, mic.elapsed, run, draft, streamResult);
        },
        onMisfire: () => {
          stream?.cancel();
          if (current() && !turnBusy) { clearPartial(); callStatus.textContent = listeningStatus(); }
        },
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
      }, { context: pendingContext });
      microphone = mic;
      pendingContext = null;
      await mic.initialize();
      if (!current()) { void mic.destroy().catch(() => {}); return; }
      syncMicrophone();
      if (!turnBusy && !micMuted) waitForReply();
    } catch (error) {
      if (pendingContext) void pendingContext.close().catch(() => {});
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
    practicePanel.hidden=true;
    mixedSession=null;
    selectedScenario = null;
    setCallState("idle", "Chọn tình huống để bắt đầu");
  }

  function setScenarioMenu(open, focusFirst = false) {
    scenarioMenu.hidden=!open;
    scenarioToggle.setAttribute('aria-expanded',String(open));
    if(open && focusFirst)scenarioOptions.querySelector('button')?.focus();
  }
  scenarioToggle.addEventListener('click',()=>setScenarioMenu(scenarioMenu.hidden));
  scenarioToggle.addEventListener('keydown',event=>{
    if(event.key==='ArrowDown'){event.preventDefault();setScenarioMenu(true,true);}
    if(event.key==='Escape'){event.preventDefault();setScenarioMenu(false);}
  });
  document.addEventListener('click',event=>{
    if(!scenarioMenu.hidden && !event.target.closest('.call-scenario-picker'))setScenarioMenu(false);
  });
  scenarioMenu.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();setScenarioMenu(false);scenarioToggle.focus();}
  });
  randomStart.addEventListener('click',()=>chooseCallScenario('mixed-any'));
  function chooseCallScenario(key) {
    if(!scenariosLoaded)return;
    setScenarioMenu(false);
          selectedScenario = key;
          practicePanel.hidden=!isMixed();
          mixedSession=null;
          practicePanel.querySelector('[data-finish-retry]').hidden=true;
          practicePanel.querySelector('[data-reason]').value='';
          practicePanel.querySelector('[data-evidence-text]').textContent='';
          practicePanel.querySelector('[data-result]').textContent='';
          practicePanel.querySelectorAll('button').forEach(b=>b.disabled=true);
          clock.textContent = new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
          setCallState("ringing", "Cuộc gọi đến", true);
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
      scenarios.sort((a,b)=>Number(b.key.startsWith('mixed-'))-Number(a.key.startsWith('mixed-')));
      scenarioOptions.replaceChildren(...scenarios.map((scenario) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = scenario.label;
        button.addEventListener("click", () => {
          chooseCallScenario(scenario.key);

        });
        return button;
      }));
      scenariosLoaded = true;
      randomStart.disabled=!scenarios.some(s=>s.key==='mixed-any');
      scenarioToggle.disabled=!scenarios.length;
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

  function setCallState(state, label, moveFocus = false) {
    const run = ++callRun;
    let finishing=null;
    clearInterval(timer);
    clearTimeout(greetingTimer);
    timer = null;
    stopAudio();
    if(state==='idle'||state==='ringing')inbox.reset();
    else if(state==='ended')inbox.ended();
    releaseMicrophone();
    micMuted = false;
    micError = "";
    updateMicButton();
    phoneAudio.muted = false;
    audioButton.setAttribute("aria-pressed", "false");
    if (sessionId) {
      finishing=finishSession(sessionId);
      sessionId = null;
    }
    if (preparedStart) {finishing=finishSession(preparedStart.session_id);preparedStart=null;}
    introPhase = "greeting";
    latestCallTurn = null;
    setTurnBusy(state === "active");
    phone.dataset.callState = state;
    if (state === 'idle' || state === 'ringing') subtitlesPanel.hidden = true;
    else if (state === 'active') subtitlesPanel.hidden = false;
    if (isMixed() && state==='ringing') {
      mixedSession=null;
      practicePanel.querySelector('[data-context]').textContent='Bạn sẽ nhận một cuộc gọi dịch vụ chưa rõ thật/giả. Bối cảnh cụ thể xuất hiện khi cuộc gọi bắt đầu.';
      practicePanel.querySelector('[data-reason]').value='';
      practicePanel.querySelector('[data-result]').textContent='';
      practicePanel.querySelector('[data-evidence-text]').textContent='';
      practicePanel.querySelector('[data-finish-retry]').hidden=true;
      practicePanel.querySelectorAll('button').forEach(b=>b.disabled=true);
    }
    practicePanel.querySelectorAll('select').forEach(select=>select.disabled=state==='active');
    if (isMixed() && state==='ended') {
      practicePanel.querySelectorAll('[data-judge]').forEach(b=>b.disabled=true);
      practicePanel.querySelectorAll('[data-event]').forEach(b=>b.disabled=true);
      const owner=mixedSession;
      Promise.resolve(finishing || true).then(saved=>{
        if(run!==callRun || mixedSession!==owner || !owner)return;
        practicePanel.querySelectorAll('[data-judge]').forEach(b=>b.disabled=!saved);
        const retry=practicePanel.querySelector('[data-finish-retry]');retry.hidden=saved;retry.disabled=false;
      });
    }
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
        setScenarioMenu(true,true);
        break;

    }
  });

  function showMode(mode, focus = true) {
    const signedIn = document.body.dataset.authenticated === 'true';
    const extraScreens = [...document.querySelectorAll('[data-workspace-screen]')];
    const allowed = ['call','message','login',...extraScreens.map(screen=>screen.dataset.workspaceScreen)];
    if (!allowed.includes(mode)) return false;
    if (!signedIn && !['help','login'].includes(mode)) return false;
    if (['rasa','scenarios','practice'].includes(mode) && document.body.dataset.userRole !== 'admin') return false;
    const previous = document.body.dataset.workspace;
    document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
    const isCall = mode === 'call';
    const enteringCall = isCall && callScreen.hidden;
    messageScreen.hidden = mode !== 'message';
    callScreen.hidden = !isCall;
    extraScreens.forEach(screen=>screen.hidden=screen.dataset.workspaceScreen!==mode);
    document.getElementById('auth-panel').hidden = mode !== 'login';
    document.getElementById('app-content').hidden = mode === 'login';
    document.body.dataset.workspace = mode;
    if (previous === 'call' && !isCall) resetCall();
    if (enteringCall) {
      loadCallScenarios();
      void CallMicrophone.preload().catch(() => {});
    }
    modeButtons.forEach(button => {
      const active = button.dataset.mode === mode;
      button.classList.toggle('is-active',active);
      if(button.tagName==='BUTTON')button.setAttribute('aria-pressed',String(active));
      if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
    });
    if (focus) {
      const target = extraScreens.find(screen=>!screen.hidden);
      if(target)target.focus({preventScroll:true});
    }
    document.dispatchEvent(new CustomEvent('arena:viewchange',{detail:{mode,previous}}));
    return true;
  }
  modeButtons.forEach(button=>button.addEventListener('click',event=>{
    event.preventDefault();showMode(button.dataset.mode);
  }));
  window.ArenaWorkspace = {show:showMode};
  const initialView = () => showMode(document.body.dataset.authenticated === 'true' ? 'message' : 'login',false);
  document.addEventListener('arena:authenticated',initialView);
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialView,{once:true});else initialView();

})();
