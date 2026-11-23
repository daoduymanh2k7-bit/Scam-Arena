/* Opt-in recordings only; audio stays in memory until explicitly saved. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const natural = ["Nếu người lạ hỏi mã xác nhận, bạn sẽ trả lời thế nào?", "Kể bằng lời của bạn cách kiểm tra một cuộc gọi đáng ngờ.", "Hãy kể một việc bạn vừa làm hôm nay, không cần nêu thông tin cá nhân."];
  let prompts = [], promptIndex = 0, items = [], visible = 10;
  let recorder, stream, timer, blob, previewURL, starting = false, stopping = false, disposed = false, uploadBusy = false, captureGeneration = 0;
  const drafts = new Map();
  let recordingKind, recordingPrompt, started;
  const statusNames = { pending: "Chờ xác nhận", confirmed: "Đã xác nhận · chưa huấn luyện", rejected: "Cần thu lại" };
  function message(text, error = false) { $("voice-message").textContent = text; $("voice-message").classList.toggle("error", error); }
  async function request(path = "", options = {}) {
    const response = await fetch("/api/voice/samples" + path, { cache: "no-store", ...options });
    if (response.status === 204) return null;
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Không xử lý được mẫu. Hãy thử lại.");
    return data;
  }
  function updatePrompt() { const options = $("voice-kind").value === "read" ? prompts : natural; $("voice-prompt").textContent = options[promptIndex % options.length] || ""; }
  function controls() {
    const active = starting || stopping || recorder?.state === "recording";
    $("voice-record").disabled = active || uploadBusy;
    $("voice-stop").disabled = !active || stopping;
    $("voice-kind").disabled = active || uploadBusy;
    $("voice-next").disabled = active || uploadBusy;
    $("voice-upload").disabled = !blob || active || uploadBusy || !$("voice-consent").checked;
    $("voice-discard").disabled = !blob || active || uploadBusy;
  }
  function releaseTracks() { stream?.getTracks().forEach(track => track.stop()); stream = null; }
  function discard() {
    blob = null;
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = null; $("voice-preview").removeAttribute("src"); $("voice-preview").hidden = true;
    $("voice-consent").checked = false; controls();
  }
  function stop() {
    captureGeneration++; starting = false; clearInterval(timer);
    if (recorder?.state === "recording") { stopping = true; recorder.stop(); }
    releaseTracks(); controls();
  }
  async function record() {
    if (starting || stopping || recorder?.state === "recording") return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { message("Thu âm cần trình duyệt hỗ trợ và HTTPS hoặc localhost.", true); return; }
    discard(); const generation = ++captureGeneration; starting = true; recordingKind = $("voice-kind").value; recordingPrompt = $("voice-prompt").textContent; controls();
    try {
      const acquired = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (!starting || disposed || generation !== captureGeneration) { acquired.getTracks().forEach(track => track.stop()); return; }
      stream = acquired;
      const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find(type => MediaRecorder.isTypeSupported(type));
      recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      const chunks = []; const current = recorder;
      current.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      current.onstop = () => {
        clearInterval(timer); stopping = false; releaseTracks();
        if (disposed) return;
        const seconds = (performance.now() - started) / 1000;
        if (seconds < 1) { message("Đoạn quá ngắn. Hãy thu ít nhất 1 giây.", true); controls(); return; }
        blob = new Blob(chunks, { type: current.mimeType || "audio/webm" });
        previewURL = URL.createObjectURL(blob); $("voice-preview").src = previewURL; $("voice-preview").hidden = false;
        message("Đã thu. Nghe lại trước khi đồng ý lưu mẫu."); controls();
      };
      current.onerror = () => { stop(); message("Thu âm gặp lỗi. Hãy thử thu lại.", true); };
      started = performance.now(); current.start(); starting = false; controls();
      message("Đang thu giọng của bạn… tự dừng sau khoảng 15 giây.");
      timer = setInterval(() => { const seconds = Math.floor((performance.now() - started) / 1000); $("voice-clock").textContent = `00:${String(seconds).padStart(2, "0")}`; if (seconds >= 14) stop(); }, 200);
    } catch (_) { if (generation !== captureGeneration) return; starting = false; releaseTracks(); controls(); message("Không mở được micro. Hãy kiểm tra quyền micro và thử lại.", true); }
  }
  async function refresh() {
    const data = await request(); items = data.items; prompts = data.prompts; updatePrompt(); render();
  }
  function element(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
  function render() {
    $("voice-total").textContent = `${items.length}/200`;
    const confirmed = items.filter(item => item.status === "confirmed");
    $("voice-confirmed").textContent = confirmed.length;
    $("voice-duration").textContent = `${(confirmed.reduce((sum, item) => sum + item.duration_ms, 0) / 60000).toFixed(1)} phút`;
    const filtered = items.filter(item => $("voice-filter").value === "all" || item.status === $("voice-filter").value);
    const list = $("voice-library"); list.replaceChildren();
    if (!filtered.length) list.append(element("p", "Chưa có mẫu ở trạng thái này. Thu đoạn đầu tiên để bắt đầu.", "voice-empty"));
    filtered.slice(0, visible).forEach(item => {
      const card = element("article", undefined, "voice-sample");
      card.append(element("span", statusNames[item.status], "voice-badge " + item.status));
      card.append(element("h3", `${item.kind === "read" ? "Đọc câu mẫu" : "Nói tự nhiên"} · ${(item.duration_ms / 1000).toFixed(1)} giây`));
      card.append(element("p", item.prompt_text, "voice-note"));
      const audio = element("audio"); audio.controls = true; audio.preload = "none"; audio.src = `/api/voice/samples/${item.sample_id}/audio`; card.append(audio);
      card.append(element("p", "Máy nghe: " + (item.machine_text || "Chưa nhận diện thử."), "voice-machine"));
      const label = element("label", "Bản chép đúng do bạn xác nhận"); const edit = element("textarea");
      edit.id = "sample-" + item.sample_id; label.htmlFor = edit.id; edit.maxLength = 2000; edit.value = drafts.get(item.sample_id) ?? item.transcript;
      edit.oninput = () => { if (edit.value === item.transcript) drafts.delete(item.sample_id); else drafts.set(item.sample_id, edit.value); }; card.append(label, edit);
      const buttons = element("div", undefined, "voice-buttons");
      function button(text, action, className = "") {
        const node = element("button", text, "button button-quiet " + className); node.type = "button";
        node.onclick = async () => {
          buttons.querySelectorAll("button").forEach(b => b.disabled = true);
          try { await action(); await refresh(); }
          catch (error) { message(error.message, true); buttons.querySelectorAll("button").forEach(b => b.disabled = false); }
        }; buttons.append(node);
      }
      const save = async status => { await request(`/${item.sample_id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ transcript: edit.value, status, revision: item.revision }) }); drafts.delete(item.sample_id); };
      button("Lưu bản nháp", async () => { await save("pending"); message("Đã lưu bản nháp, chưa xác nhận."); });
      button("Tôi đã nghe lại · Xác nhận", async () => { await save("confirmed"); message("Đã xác nhận bản chép. Chưa đưa vào huấn luyện model."); });
      button("Cần thu lại", async () => { await save("rejected"); message("Đã đánh dấu mẫu cần thu lại."); });
      if (item.status === "pending") button("Nhận diện thử", async () => {
        if (edit.value !== item.transcript) throw new Error("Hãy lưu bản nháp trước khi nhận diện thử để giữ phần bạn vừa sửa.");
        message("Đang nhận diện thử. Bạn không cần nhận diện thử để tự chép và xác nhận.");
        await request(`/${item.sample_id}/transcribe`, { method: "POST" }); message("Đã nhận diện thử. Hãy đối chiếu với âm thanh, không tự coi đây là bản đúng.");
      });
      button("Xóa mẫu", async () => { if (!confirm("Xóa vĩnh viễn bản thu và bản chép mẫu này?")) return; await request(`/${item.sample_id}`, { method: "DELETE" }); drafts.delete(item.sample_id); message("Đã xóa mẫu."); }, "voice-delete");
      card.append(buttons); list.append(card);
    });
    $("voice-more").hidden = filtered.length <= visible;
  }
  $("voice-record").onclick = record; $("voice-stop").onclick = stop; $("voice-discard").onclick = discard;
  $("voice-consent").onchange = controls;
  $("voice-kind").onchange = () => { promptIndex = 0; updatePrompt(); };
  $("voice-next").onclick = () => { promptIndex++; updatePrompt(); };
  $("voice-filter").onchange = () => { visible = 10; render(); };
  $("voice-more").onclick = () => { visible += 10; render(); };
  $("voice-refresh").onclick = () => refresh().catch(error => message(error.message, true));
  $("voice-upload").onclick = async () => {
    if (!blob || !$("voice-consent").checked || uploadBusy) return;
    uploadBusy = true; controls(); message("Đang lưu mẫu…");
    try {
      const form = new FormData(); form.append("audio", blob, "sample"); form.append("kind", recordingKind); form.append("prompt_text", recordingPrompt); form.append("consent", "true");
      await request("", { method: "POST", body: form }); discard(); await refresh(); message("Mẫu đã lưu riêng trong tài khoản. Tiếp theo: nghe lại và xác nhận bản chép.");
    } catch (error) { message(error.message, true); } finally { uploadBusy = false; controls(); }
  };
  window.addEventListener("pagehide", () => { disposed = true; stop(); if (previewURL) URL.revokeObjectURL(previewURL); });
  window.addEventListener("beforeunload", event => { if (blob || drafts.size || starting || recorder?.state === "recording") { event.preventDefault(); event.returnValue = ""; } });
  (async () => {
    try {
      const response = await fetch("/api/auth/me", { cache: "no-store" });
      if (!response.ok) { message("Hãy quay lại Scam Arena và đăng nhập để quản lý giọng của bạn.", true); return; }
      $("voice-account").textContent = (await response.json()).username;
      await refresh(); $("voice-content").hidden = false;
    } catch (error) { message(error.message, true); }
  })();
})();
