(() => {
  const $ = (id) => document.getElementById(`rasa-review-${id}`);
  const dialog = $("dialog");
  const endpoint = "/api/arena/admin/rasa-review";
  const pageSize = 25;
  let offset = 0;
  let busy = false;

  const intents = [
    ["", "Chờ duyệt"],
    ["verify", "Tự xác minh"],
    ["refuse", "Từ chối"],
    ["doubt", "Nghi ngờ"],
    ["comply", "Đồng ý làm theo"],
    ["share_sensitive", "Chia sẻ dữ liệu nhạy cảm"],
    ["transfer_money", "Chuyển tiền"],
    ["hang_up", "Dừng liên lạc"],
    ["unknown", "Chưa rõ ý định"],
    ["skip", "Bỏ qua"],
  ];

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function picker(options, value, label) {
    const select = node("select");
    select.setAttribute("aria-label", label);
    for (const [key, caption] of options) select.add(new Option(caption, key));
    select.value = value ?? "";
    return select;
  }

  async function request(path = "", method = "GET", body) {
    const response = await fetch(endpoint + path, {
      method,
      cache: "no-store",
      ...(body && { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "Không thể xử lý yêu cầu duyệt mẫu.");
    }
    return data;
  }

  function render(data) {
    $("count").textContent = `${data.pending} chờ duyệt · ${data.reviewed} đã xử lý`;
    const accounts = new Map();
    $("speakers").replaceChildren(...data.speakers.map((speaker, index) => {
      const name = `Tài khoản ${index + 1}`;
      accounts.set(speaker.speaker, name);
      const row = node("div", "", "rasa-speaker-row");
      const caption = node("label", `${name} · ${speaker.count} mẫu`);
      const select = picker(
        [["", "Chưa chọn nhóm"], ["train", "Huấn luyện"], ["holdout", "Kiểm thử"]],
        speaker.split, `Nhóm của ${name}`,
      );
      select.disabled = speaker.locked;
      select.addEventListener("change", async () => {
        const saved = await run(() => request(`/speakers/${encodeURIComponent(speaker.speaker)}`, "PATCH", {
          expected_split: speaker.split, split: select.value || null,
        }));
        if (!saved) select.value = speaker.split ?? "";
      });
      caption.append(select);
      row.append(caption);
      if (speaker.locked) row.append(node("small", "Đã khóa nhóm sau khi xuất"));
      return row;
    }));
    $("samples").replaceChildren(...data.samples.map((sample, index) => {
      const row = node("article", "", "rasa-sample-row");
      const source = sample.style === "whisper" ? "Cuộc gọi · Whisper" : "Tin nhắn";
      const account = accounts.get(sample.speaker) ?? "Tài khoản";
      row.append(
        node("p", `${account} · ${source}`, "rasa-review-note"),
        node("p", sample.text, "rasa-sample-text"),
      );
      const form = node("form", "", "rasa-sample-actions");
      const select = picker(intents, sample.intent, `Nhãn mẫu ${offset + index + 1}`);
      const save = node("button", "Lưu nhãn", "admin-small-button");
      save.type = "submit";
      save.disabled = true;
      select.addEventListener("change", () => { save.disabled = select.value === (sample.intent ?? ""); });
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const saved = await run(() => request(`/samples/${encodeURIComponent(sample.sample)}`, "PATCH", {
          expected_intent: sample.intent, intent: select.value || null,
        }));
        if (saved) $("count").textContent += " · Đã lưu";
      });
      form.append(select, save);
      row.append(form);
      return row;
    }));
    if (!data.samples.length) $("samples").append(node("p", "Không có mẫu trong danh sách này.", "rasa-review-note"));
    $("pages").hidden = data.total <= pageSize;
    $("prev").disabled = offset === 0;
    $("next").disabled = offset + pageSize >= data.total;
    $("range").textContent = `${offset + 1}–${offset + data.samples.length} / ${data.total}`;
  }

  async function run(action) {
    if (busy) return false;
    busy = true;
    $("error").hidden = true;
    dialog.setAttribute("aria-busy", "true");
    dialog.querySelector(".rasa-review-columns").inert = true;
    $("filter").disabled = true;
    $("collect").disabled = true;
    try {
      const result = action ? await action() : null;
      let data = await request(`?status=${$("filter").value}&offset=${offset}&limit=${pageSize}`);
      if (!data.samples.length && offset > 0) {
        offset = 0;
        data = await request(`?status=${$("filter").value}&limit=${pageSize}`);
      }
      render(data);
      if (result?.added != null) $("count").textContent += ` · Thêm ${result.added} mẫu`;
      return true;
    } catch (error) {
      $("error").textContent = error.message;
      $("error").hidden = false;
      return false;
    } finally {
      busy = false;
      dialog.removeAttribute("aria-busy");
      dialog.querySelector(".rasa-review-columns").inert = false;
      $("filter").disabled = false;
      $("collect").disabled = false;
    }
  }

  document.addEventListener("arena:viewchange", event => {
    if(event.detail.mode!=="rasa")return;
    offset = 0;
    run();
  });
  $("collect").addEventListener("click", () => run(() => request("/collect", "POST")));
  $("filter").addEventListener("change", () => { offset = 0; run(); });
  $("prev").addEventListener("click", () => { offset -= pageSize; run(); });
  $("next").addEventListener("click", () => { offset += pageSize; run(); });
})();
