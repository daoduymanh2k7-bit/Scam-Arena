(() => {
  const $ = (id) => document.getElementById(id);
  const intentNames = {
    verify: "Xác minh độc lập", refuse: "Từ chối", doubt: "Nghi ngờ",
    comply: "Làm theo", share_sensitive: "Chia sẻ thông tin nhạy cảm",
    transfer_money: "Chuyển tiền", hang_up: "Kết thúc cuộc gọi", unknown: "Chưa rõ",
  };

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
        score.textContent = item.awaiting_judgement ? 'Chưa đánh giá' : `${item.total_score}/100`;
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
              transcript.appendChild(line);
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

  $("arena-history-refresh").addEventListener("click", loadHistory);
  window.ArenaHistory = { refreshAll: loadHistory };
})();
