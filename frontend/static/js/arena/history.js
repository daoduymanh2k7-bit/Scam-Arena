(() => {
  const $ = (id) => document.getElementById(id);
  const intentNames = {
    verify: "Xác minh độc lập", refuse: "Từ chối", doubt: "Nghi ngờ",
    comply: "Làm theo", share_sensitive: "Chia sẻ thông tin nhạy cảm",
    transfer_money: "Chuyển tiền", hang_up: "Kết thúc cuộc gọi", unknown: "Chưa rõ",
  };
  const intentValues = Object.keys(intentNames).filter((key) => key !== "unknown");

  async function loadHistory() {
    const list = $("arena-history-list"), empty = $("arena-history-empty"), error = $("arena-history-error");
    error.hidden = true;
    try {
      const sessions = await Api.callHistory();
      list.replaceChildren();
      empty.hidden = sessions.length !== 0;
      sessions.forEach((item) => {
        const card = document.createElement("article");
        card.className = "history-card";
        const heading = document.createElement("div");
        heading.className = "history-card-heading";
        const title = document.createElement("strong");
        title.textContent = item.scenario_title;
        const score = document.createElement("span");
        score.textContent = `${item.total_score}/100`;
        heading.append(title, score);
        const meta = document.createElement("p");
        const outcome = item.outcome === "safe" ? "An toàn" : item.outcome === "scammed" ? "Rủi ro" : item.outcome === "timeout" ? "Chưa đủ dữ liệu" : "Đang chơi";
        meta.textContent = `${new Date(item.started_at).toLocaleString("vi-VN")} · ${item.turn_count} lượt · ${outcome}`;
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = "Xem hội thoại đã lưu";
        const transcript = document.createElement("div");
        transcript.className = "saved-transcript";
        details.append(summary, transcript);
        details.addEventListener("toggle", async () => {
          if (!details.open || transcript.dataset.loaded) return;
          try {
            const data = await Api.callTranscript(item.session_id);
            data.messages.forEach((message) => {
              const line = document.createElement("p");
              const role = message.role === "player" ? "Bạn" : "Người gọi";
              const intent = message.intent ? ` · ${intentNames[message.intent] || message.intent}` : "";
              line.textContent = `${role}${intent}: ${message.text}`;
              line.className = `saved-message ${message.role}`;
              if (message.role === "player" && message.turn_no) {
                const wrapper = document.createElement("div");
                wrapper.className = "saved-message-row";
                const flag = document.createElement("button");
                flag.type = "button"; flag.className = "button button-quiet flag-turn";
                flag.textContent = "Báo máy hiểu sai";
                flag.addEventListener("click", async () => {
                  flag.disabled = true;
                  try {
                    await Api.flagCallTurn(item.session_id, message.turn_no);
                    flag.textContent = "Đã gửi duyệt";
                    setTimeout(loadCandidates, 1000);
                  } catch (err) { flag.textContent = `Lỗi: ${err.message}`; flag.disabled = false; }
                });
                wrapper.append(line, flag);
                transcript.appendChild(wrapper);
              } else transcript.appendChild(line);
            });
            transcript.dataset.loaded = "true";
          } catch (err) {
            transcript.textContent = `Không tải được hội thoại: ${err.message}`;
          }
        });
        card.append(heading, meta, details);
        list.appendChild(card);
      });
    } catch (err) {
      error.textContent = `Không tải được lịch sử: ${err.message}`;
      error.hidden = false;
    }
  }

  async function loadCandidates() {
    const list = $("arena-review-list"), empty = $("arena-review-empty"), error = $("arena-review-error");
    error.hidden = true;
    try {
      const candidates = await Api.intentCandidates();
      list.replaceChildren();
      empty.hidden = candidates.length !== 0;
      candidates.forEach((candidate) => {
        const card = document.createElement("article");
        card.className = "review-card";
        const heading = document.createElement("strong");
        heading.textContent = `${candidate.scenario_title} · ${candidate.stage}`;
        const caller = document.createElement("p");
        caller.className = "review-context";
        caller.textContent = `Người gọi: ${candidate.caller_text}`;
        const player = document.createElement("blockquote");
        player.textContent = `Người chơi: ${candidate.user_text_masked}`;
        const suggestion = document.createElement("p");
        suggestion.className = "muted-note";
        const statusText = candidate.analysis_status === "analyzed" ? `LLM gợi ý: ${intentNames[candidate.suggested_intent] || "Chưa rõ"} (${Math.round((candidate.confidence || 0) * 100)}%)` : candidate.analysis_status === "not_configured" ? "LLM chưa cấu hình; bạn có thể gán nhãn thủ công." : candidate.analysis_status === "failed" ? "LLM chưa phân tích được; bạn có thể gán nhãn thủ công." : "Đang chờ LLM phân tích…";
        const detectedText = `Máy đã gán: ${intentNames[candidate.detected_intent] || candidate.detected_intent}${candidate.source_reason === "player_flagged" ? " · Người chơi báo máy hiểu sai" : " · Máy chưa nhận diện"}`;
        suggestion.textContent = `${detectedText}. ${statusText}${candidate.rationale ? ` · ${candidate.rationale}` : ""}`;
        const fields = document.createElement("div");
        fields.className = "review-fields";
        const select = document.createElement("select");
        select.setAttribute("aria-label", "Ý định đúng");
        const placeholder = document.createElement("option");
        placeholder.value = ""; placeholder.textContent = "Chọn ý định đã xác nhận";
        select.appendChild(placeholder);
        intentValues.forEach((intent) => {
          const option = document.createElement("option");
          option.value = intent; option.textContent = intentNames[intent];
          if (candidate.suggested_intent === intent) option.selected = true;
          select.appendChild(option);
        });
        const phrase = document.createElement("input");
        phrase.type = "text"; phrase.maxLength = 120;
        phrase.setAttribute("aria-label", "Cụm từ nhận diện sau khi duyệt");
        phrase.value = candidate.suggested_phrase || candidate.user_text_masked.slice(0, 120);
        const actions = document.createElement("div");
        actions.className = "review-actions";
        const approve = document.createElement("button");
        approve.type = "button"; approve.className = "button button-primary"; approve.textContent = "Duyệt và thêm luật";
        approve.addEventListener("click", async () => {
          if (!select.value) { error.textContent = "Hãy chọn ý định đúng trước khi duyệt."; error.hidden = false; return; }
          approve.disabled = true;
          try {
            await Api.approveIntentCandidate(candidate.candidate_id, select.value, phrase.value.trim());
            await Promise.all([loadCandidates(), loadHistory()]);
          } catch (err) { error.textContent = `Không duyệt được: ${err.message}`; error.hidden = false; approve.disabled = false; }
        });
        const reject = document.createElement("button");
        reject.type = "button"; reject.className = "button button-quiet"; reject.textContent = "Bỏ qua";
        reject.addEventListener("click", async () => {
          reject.disabled = true;
          try { await Api.rejectIntentCandidate(candidate.candidate_id); await loadCandidates(); }
          catch (err) { error.textContent = `Không bỏ qua được: ${err.message}`; error.hidden = false; reject.disabled = false; }
        });
        actions.append(approve, reject);
        fields.append(select, phrase);
        card.append(heading, caller, player, suggestion, fields, actions);
        list.appendChild(card);
      });
    } catch (err) {
      error.textContent = `Không tải được hàng đợi duyệt: ${err.message}`;
      error.hidden = false;
    }
  }

  async function refreshAll() { await Promise.all([loadHistory(), loadCandidates()]); }
  $("arena-history-refresh").addEventListener("click", loadHistory);
  $("arena-review-refresh").addEventListener("click", loadCandidates);
  refreshAll();
  window.ArenaHistory = { refreshAll };
})();
