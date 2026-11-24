(() => {
  const dialog = document.getElementById("admin-dialog");
  const openButton = document.getElementById("admin-open");
  const scenarioSelect = document.getElementById("admin-scenario-select");
  const stageLinesTitle = document.getElementById("admin-stage-lines-title");
  const stageLines = document.getElementById("admin-stage-lines");
  const graph = document.getElementById("admin-graph");
  const nodeOpen = document.getElementById("admin-node-open");
  const overview = document.getElementById("admin-scenario-overview-content");
  const overviewDialog = document.getElementById("admin-overview-dialog");
  const overviewButton = document.getElementById("admin-overview-open");
  const error = document.getElementById("admin-error");
  const status = document.getElementById("admin-scenario-status");
  const graphScroll = document.getElementById("admin-graph-scroll");
  const zoomLabel = document.getElementById("admin-zoom-level");
  const linesDialog = document.getElementById("admin-lines-dialog");
  const linesContent = document.getElementById("admin-lines-content");
  if (!dialog || !openButton) return;

  const NS = "http://www.w3.org/2000/svg";
  const labels = {
    verify: "Tự xác minh", refuse: "Từ chối", doubt: "Nghi ngờ", comply: "Đồng ý",
    share_sensitive: "Chia sẻ dữ liệu", transfer_money: "Chuyển tiền", hang_up: "Dừng liên lạc", unknown: "Chưa rõ",
  };
  const actionLabels = {
    none: "Không yêu cầu", share_sensitive: "Chia sẻ thông tin nhạy cảm", transfer_money: "Chuyển tiền",
    install_app: "Cài ứng dụng", click_link: "Bấm liên kết", share_screen: "Chia sẻ màn hình",
    keep_secret: "Giữ bí mật", other: "Khác",
  };
  let scenarios = [];
  let selectedScenarioKey = null;
  let baseWidth = 1, baseHeight = 1, mapZoom = 1;
  let resetTimer = null, resetFrame = null;

  function setZoom(nextZoom, anchorX = null, anchorY = null) {
    const previous = mapZoom;
    mapZoom = Math.min(2.4, Math.max(0.2, nextZoom));
    graph.setAttribute("width", Math.round(baseWidth * mapZoom));
    graph.setAttribute("height", Math.round(baseHeight * mapZoom));
    zoomLabel.textContent = `${Math.round(mapZoom * 100)}%`;
    if (anchorX != null && anchorY != null) {
      graphScroll.scrollLeft = (graphScroll.scrollLeft + anchorX) * mapZoom / previous - anchorX;
      graphScroll.scrollTop = (graphScroll.scrollTop + anchorY) * mapZoom / previous - anchorY;
    }
  }
  function fitGraph() {
    const availableWidth = Math.max(1, graphScroll.clientWidth - 24);
    const availableHeight = Math.max(1, graphScroll.clientHeight - 24);
    const fittedZoom = Math.min(1, availableWidth / baseWidth, availableHeight / baseHeight);
    setZoom(fittedZoom);
    graphScroll.scrollLeft = 0;
    graphScroll.scrollTop = 0;
  }
  function pointerInGraph(event) {
    const point = graph.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(graph.getScreenCTM().inverse());
  }

  function element(tag, attrs = {}, text = "") {
    const item = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([key, value]) => item.setAttribute(key, value));
    if (text) item.textContent = text;
    return item;
  }
  function addHtml(parent, tag, className, value) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    item.textContent = value ?? "";
    parent.appendChild(item);
    return item;
  }
  function nodeTitle(node) {
    if (node.is_terminal) return node.outcome === "safe" ? "Kết thúc · An toàn"
      : node.outcome === "scammed" ? "Kết thúc · Rủi ro" : "Kết thúc · Hết thời gian";
    return node.node_key.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
  }
  function appendDialogueLines(parent, node) {
    if (!node.lines?.length) {
      addHtml(parent, "p", "", "Giai đoạn này chưa có câu thoại nào trong kho.");
      return;
    }
    const lineList = document.createElement("div");
    lineList.className = "admin-dialogue-lines";
    node.lines.forEach((line, index) => {
      const entry = document.createElement("blockquote");
      if (!line.enabled) entry.classList.add("is-disabled");
      const badge = document.createElement("span");
      badge.className = "admin-line-badge";
      const sourceLabel = line.source === "llm" ? "LLM" : "Cố định";
      const intentLabel = line.intent ? (labels[line.intent] || line.intent) : "Mở đầu";
      badge.textContent = `#${index + 1} · ${sourceLabel} · ${intentLabel}${line.is_reprompt ? " · hỏi lại" : ""}${line.enabled ? "" : " · đã tắt"}${line.source === "llm" ? ` · ưu tiên ${line.preference_score}` : ""}`;
      entry.append(badge, document.createTextNode(line.line_text));
      lineList.appendChild(entry);
    });
    parent.appendChild(lineList);
  }
  function openNodeDetails(scenario, node) {
    linesDialog.querySelector("#admin-lines-title").textContent = `${scenario.title} · ${nodeTitle(node)}`;
    renderNodeDetails(linesContent, scenario, node);
    linesContent.scrollTop = 0;
    if (!linesDialog.open) linesDialog.show();
  }
  function renderNodeDetails(details, scenario, node) {
    details.replaceChildren();
    if (node.is_terminal) {
      addHtml(details, "p", "", `Kết quả của nhánh này: ${node.outcome === "safe" ? "an toàn" : node.outcome === "scammed" ? "không an toàn" : "hết thời gian"}.`);
    } else {
      addHtml(details, "p", "", `Giai đoạn: ${node.stage || node.node_key} · Số lượt tối đa: ${node.max_turns}`);
      addHtml(details, "p", "", `Mục tiêu: ${node.objective || "Chưa có mô tả."}`);
      addHtml(details, "p", "", `Chiến thuật: ${node.tactic || "Chưa ghi chú."}`);
      addHtml(details, "p", "", `Hành động người gọi hướng tới: ${actionLabels[node.requested_action] || node.requested_action}`);
    }
    const outgoing = scenario.transitions.filter((edge) => edge.from_node_id === node.node_id);
    if (node.timeout_next_node_id) outgoing.push({ intent: "timeout", to_node_id: node.timeout_next_node_id, score_delta: 0, feedback: "Tự chuyển sau khi chờ quá thời gian." });
    if (outgoing.length) {
      addHtml(details, "h4", "", "Nhánh và điểm");
      const list = document.createElement("ul");
      outgoing.forEach((edge) => {
        const target = scenario.nodes.find((item) => item.node_id === edge.to_node_id);
        const item = document.createElement("li");
        item.textContent = `${edge.intent === "timeout" ? "Hết thời gian" : labels[edge.intent] || edge.intent} → ${target ? nodeTitle(target) : "node không tồn tại"} · ${edge.score_delta > 0 ? "+" : ""}${edge.score_delta} điểm${edge.critical ? " · cảnh báo nghiêm trọng" : ""}${edge.feedback ? ` — ${edge.feedback}` : ""}`;
        list.appendChild(item);
      });
      details.appendChild(list);
    }
  }
  function drawGraph(scenario) {
    clearTimeout(resetTimer);
    if (resetFrame != null) cancelAnimationFrame(resetFrame);
    resetTimer = null;
    resetFrame = null;
    graph.replaceChildren();
    const nodes = scenario.nodes || [];
    const byId = new Map(nodes.map((node) => [node.node_id, node]));
    const start = nodes.find((node) => node.is_start);
    const layers = new Map();
    const distances = new Map();
    if (start) {
      distances.set(start.node_id, 0);
      const queue = [start];
      while (queue.length) {
        const current = queue.shift();
        const distance = distances.get(current.node_id);
        const nextIds = (scenario.transitions || []).filter((edge) => edge.from_node_id === current.node_id).map((edge) => edge.to_node_id);
        if (current.timeout_next_node_id) nextIds.push(current.timeout_next_node_id);
        nextIds.forEach((id) => {
          if (byId.has(id) && !distances.has(id)) {
            distances.set(id, distance + 1);
            queue.push(byId.get(id));
          }
        });
      }
    }
    const furthest = Math.max(0, ...nodes.filter((node) => !node.is_terminal).map((node) => distances.get(node.node_id) ?? 0));
    const terminalLevel = furthest + 1;
    nodes.forEach((node) => {
      const level = node.is_terminal ? terminalLevel : (distances.get(node.node_id) ?? furthest + 1);
      if (!layers.has(level)) layers.set(level, []);
      layers.get(level).push(node);
    });
    layers.forEach((items) => items.sort((a, b) => Number(b.is_start) - Number(a.is_start) || Number(a.is_terminal) - Number(b.is_terminal) || String(a.node_key).localeCompare(String(b.node_key))));
    const colWidth = 228, rowHeight = 124, nodeWidth = 142, nodeHeight = 70, left = 22, top = 26;
    const maxRows = Math.max(1, ...[...layers.values()].map((items) => items.length));
    const cols = Math.max(1, ...layers.keys()) + 1;
    const width = left * 2 + cols * colWidth;
    const height = top * 2 + maxRows * rowHeight;
    baseWidth = width;
    baseHeight = height;
    graph.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const defs = element("defs");
    const marker = element("marker", { id: "graph-arrow", viewBox: "0 0 10 10", refX: "8", refY: "5", markerWidth: "6", markerHeight: "6", orient: "auto-start-reverse" });
    marker.appendChild(element("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: "#a49acb" }));
    defs.appendChild(marker);
    graph.appendChild(defs);
    const positions = new Map();
    const initialPositions = new Map();
    layers.forEach((items, level) => items.forEach((node, row) => {
      const position = { x: left + level * colWidth, y: top + row * rowHeight };
      positions.set(node.node_id, position);
      initialPositions.set(node.node_id, { ...position });
    }));
    const edgeLayer = element("g", { class: "graph-edges" });
    const nodeLayer = element("g", { class: "graph-nodes" });
    graph.append(edgeLayer, nodeLayer);
    const nodeElements = new Map();

    const edges = [...(scenario.transitions || []).map((edge) => ({ ...edge, timeout: false }))];
    nodes.filter((node) => node.timeout_next_node_id).forEach((node) => edges.push({ from_node_id: node.node_id, to_node_id: node.timeout_next_node_id, intent: "timeout", score_delta: 0, timeout: true }));
    const outgoing = new Map();
    edges.forEach((edge, index) => {
      if (!byId.has(edge.from_node_id) || !byId.has(edge.to_node_id)) return;
      if (!outgoing.has(edge.from_node_id)) outgoing.set(edge.from_node_id, new Map());
      const destinations = outgoing.get(edge.from_node_id);
      if (!destinations.has(edge.to_node_id)) destinations.set(edge.to_node_id, []);
      destinations.get(edge.to_node_id).push(index);
    });
    let hoveredPathNodeId = null;
    let lockedPathNodeId = null;
    let lockedPathIndex = 0;
    stageLinesTitle.textContent = "Lời thoại theo giai đoạn";
    stageLines.replaceChildren();
    addHtml(stageLines, "p", "", "Bấm vào một thẻ trên sơ đồ để xem lời thoại.");
    nodeOpen.disabled = true;
    nodeOpen.onclick = () => {
      const node = byId.get(lockedPathNodeId);
      if (node) openNodeDetails(scenario, node);
    };
    const pathStatus = document.getElementById("admin-path-status");
    const routeCache = new Map();
    const maxRoutes = 120;
    function getPathsTo(targetId) {
      if (!start || targetId == null) return { paths: [], truncated: false };
      if (routeCache.has(targetId)) return routeCache.get(targetId);
      const found = [];
      function visit(currentId, visitedNodes, pathEdges) {
        if (currentId === targetId) {
          found.push({ nodes: visitedNodes, edges: pathEdges });
          return;
        }
        for (const [nextId, indexes] of outgoing.get(currentId) || []) {
          if (found.length > maxRoutes) break;
          if (visitedNodes.includes(nextId)) continue;
          visit(nextId, [...visitedNodes, nextId], [...pathEdges, indexes[0]]);
        }
      }
      visit(start.node_id, [start.node_id], []);
      found.sort((a, b) => a.nodes.length - b.nodes.length);
      const result = { paths: found.slice(0, maxRoutes), truncated: found.length > maxRoutes };
      routeCache.set(targetId, result);
      return result;
    }
    function applyPathHighlight() {
      const targetId = hoveredPathNodeId ?? lockedPathNodeId;
      const { paths, truncated } = getPathsTo(targetId);
      const selectedIndex = targetId === lockedPathNodeId ? lockedPathIndex : 0;
      const path = paths.length ? paths[Math.min(selectedIndex, paths.length - 1)] : null;
      const pathNodes = new Set(path?.nodes || []);
      const pathEdges = new Set(path?.edges || []);
      nodeElements.forEach((group, id) => {
        const onPath = pathNodes.has(id);
        group.classList.toggle("is-dim", !onPath);
        group.classList.toggle("is-path", onPath);
        group.classList.toggle("is-active-target", id === targetId);
      });
      edgeLayer.querySelectorAll("[data-edge-index]").forEach((item) => {
        const onPath = pathEdges.has(Number(item.dataset.edgeIndex));
        item.classList.toggle("is-path", onPath);
      });
      if (pathStatus) {
        if (targetId == null) pathStatus.textContent = "Bấm vào thẻ để ghim tuyến. Bấm lại để đổi tuyến.";
        else {
          const target = byId.get(targetId);
          const prefix = targetId === lockedPathNodeId ? "Tuyến" : "Xem trước tuyến";
          const routeNumber = selectedIndex + 1;
          pathStatus.textContent = paths.length
            ? `${prefix} ${routeNumber}/${paths.length}${truncated ? "+" : ""} tới ${nodeTitle(target)}`
            : `Không có đường đi từ node bắt đầu tới ${nodeTitle(target)}.`;
        }
      }
    }
    function selectPath(node) {
      if (lockedPathNodeId === node.node_id) {
        const { paths } = getPathsTo(node.node_id);
        if (paths.length > 1) lockedPathIndex = (lockedPathIndex + 1) % paths.length;
      } else {
        lockedPathNodeId = node.node_id;
        lockedPathIndex = 0;
        stageLinesTitle.textContent = `${nodeTitle(node)} · ${node.lines?.length || 0} câu`;
        stageLines.replaceChildren();
        appendDialogueLines(stageLines, node);
        stageLines.scrollTop = 0;
      }
      nodeOpen.disabled = false;
      applyPathHighlight();
    }
    function drawEdges() {
      edgeLayer.replaceChildren();
      edges.forEach((edge, edgeIndex) => {
        const from = positions.get(edge.from_node_id), to = positions.get(edge.to_node_id);
        if (!from || !to) return;
        const indexes = outgoing.get(edge.from_node_id).get(edge.to_node_id);
        if (edgeIndex !== indexes[0]) return;
        const x1 = from.x + nodeWidth, y1 = from.y + nodeHeight / 2;
        const x2 = to.x, y2 = to.y + nodeHeight / 2;
        const forward = x2 > x1;
        const bendX = forward ? (x2 - x1) * .45 : Math.max(36, Math.min(110, Math.abs(y2 - y1) * .38));
        const bendY = forward ? 0 : bendX;
        const curve = `M ${x1} ${y1} C ${x1 + bendX} ${y1 + bendY}, ${x2 - bendX} ${y2 + bendY}, ${x2} ${y2}`;
        const target = byId.get(edge.to_node_id);
        const targetClass = target?.outcome === "safe" ? "safe" : target?.outcome === "scammed" ? "risk" : "normal";
        const branches = indexes.map((index) => edges[index]);
        const branchLabels = branches.map((branch) => branch.timeout
          ? "Hết giờ"
          : `${labels[branch.intent] || branch.intent} ${branch.score_delta > 0 ? "+" : ""}${branch.score_delta}`);
        const timeoutOnly = branches.every((branch) => branch.timeout);
        const line = element("path", { d: curve, "data-edge-index": edgeIndex, class: `graph-edge${timeoutOnly ? " timeout" : ""} ${targetClass}` });
        line.appendChild(element("title", {}, branchLabels.join("\n")));
        const caption = branches.length > 1 ? `${branches.length} điều kiện` : branchLabels[0];
        const labelX = (x1 + x2) / 2;
        const labelY = (y1 + y2) / 2 + bendY * .75 - 5;
        const textWidth = Math.min(120, Math.max(54, caption.length * 6.1 + 12));
        edgeLayer.append(
          line,
          element("rect", { x: labelX - textWidth / 2, y: labelY - 11, width: textWidth, height: 19, rx: 6, "data-edge-index": edgeIndex, class: "graph-edge-label-bg" }),
          element("text", { x: labelX, y: labelY + 2, "data-edge-index": edgeIndex, class: "graph-edge-label", "text-anchor": "middle" }, caption)
        );
      });
      applyPathHighlight();
    }
    drawEdges();
    function hasMovedNodes() {
      return [...positions].some(([id, position]) => {
        const home = initialPositions.get(id);
        return Math.abs(position.x - home.x) > 0.5 || Math.abs(position.y - home.y) > 0.5;
      });
    }
    function scheduleReturnHome() {
      clearTimeout(resetTimer);
      if (!hasMovedNodes()) return;
      resetTimer = setTimeout(() => {
        resetTimer = null;
        const starts = new Map([...positions].map(([id, position]) => [id, { ...position }]));
        const startedAt = performance.now();
        const duration = 900;
        function animate(now) {
          const progress = Math.min(1, (now - startedAt) / duration);
          const eased = 1 - Math.pow(1 - progress, 3);
          positions.forEach((position, id) => {
            const home = initialPositions.get(id);
            const from = starts.get(id);
            const x = from.x + (home.x - from.x) * eased;
            const y = from.y + (home.y - from.y) * eased;
            positions.set(id, { x, y });
            nodeElements.get(id)?.setAttribute("transform", `translate(${x - home.x} ${y - home.y})`);
          });
          drawEdges();
          if (progress < 1) {
            resetFrame = requestAnimationFrame(animate);
          } else {
            positions.forEach((_, id) => positions.set(id, { ...initialPositions.get(id) }));
            nodeElements.forEach((group) => group.removeAttribute("transform"));
            drawEdges();
            resetFrame = null;
          }
        }
        resetFrame = requestAnimationFrame(animate);
      }, 3000);
    }
    nodes.forEach((node) => {
      const { x, y } = positions.get(node.node_id);
      const type = node.is_terminal ? (node.outcome === "safe" ? "safe" : node.outcome === "scammed" ? "risk" : "timeout") : node.is_start ? "start" : "stage";
      const group = element("g", { class: `graph-node ${type}`, tabindex: "0", role: "button", "aria-label": nodeTitle(node), "data-node-id": node.node_id });
      nodeElements.set(node.node_id, group);
      group.appendChild(element("rect", { x, y, width: nodeWidth, height: nodeHeight, rx: 13, class: "graph-node-card" }));
      group.setAttribute("aria-label", `${nodeTitle(node)} · ${node.lines?.length || 0} câu thoại · bấm để ghim tuyến, bấm đúp để mở chi tiết`);
      group.appendChild(element("text", { x: x + 10, y: y + 16, class: "graph-node-tag" }, node.is_terminal ? "KẾT THÚC" : node.is_start ? "BẮT ĐẦU" : "GIAI ĐOẠN"));
      const title = nodeTitle(node);
      const titleLines = title.match(/.{1,16}(?:\s|$)|.{1,16}/g) || [title];
      titleLines.slice(0, 2).forEach((line, index) => group.appendChild(element("text", { x: x + 10, y: y + 33 + index * 13, class: "graph-node-title" }, line.trim())));
      const note = node.is_terminal ? (node.outcome || "") : `${node.max_turns} lượt · ${node.lines?.length || 0} câu`;
      group.appendChild(element("text", { x: x + 10, y: y + 61, class: "graph-node-note" }, note));
      let drag = null;
      const previewNode = () => {
        hoveredPathNodeId = node.node_id;
        applyPathHighlight();
      };
      group.addEventListener("mouseenter", previewNode);
      group.addEventListener("focus", previewNode);
      group.addEventListener("mouseleave", () => {
        if (drag) return;
        hoveredPathNodeId = null;
        applyPathHighlight();
      });
      group.addEventListener("blur", () => {
        hoveredPathNodeId = null;
        applyPathHighlight();
      });
      group.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        clearTimeout(resetTimer);
        resetTimer = null;
        if (resetFrame != null) cancelAnimationFrame(resetFrame);
        resetFrame = null;
        nodeLayer.appendChild(group);
        group.setPointerCapture(event.pointerId);
        hoveredPathNodeId = node.node_id;
        applyPathHighlight();
        const position = positions.get(node.node_id);
        const graphPoint = pointerInGraph(event);
        drag = { pointerId: event.pointerId, clientX: event.clientX, clientY: event.clientY,
          graphX: graphPoint.x, graphY: graphPoint.y, startX: position.x, startY: position.y, moved: false };
      });
      group.addEventListener("pointermove", (event) => {
        if (!drag || event.pointerId !== drag.pointerId) return;
        const dxScreen = event.clientX - drag.clientX;
        const dyScreen = event.clientY - drag.clientY;
        if (!drag.moved && Math.hypot(dxScreen, dyScreen) < 4) return;
        drag.moved = true;
        const graphPoint = pointerInGraph(event);
        const x = Math.max(8, Math.min(baseWidth - nodeWidth - 8, drag.startX + graphPoint.x - drag.graphX));
        const y = Math.max(8, Math.min(baseHeight - nodeHeight - 8, drag.startY + graphPoint.y - drag.graphY));
        const collides = [...positions.entries()].some(([otherId, other]) => {
          if (otherId === node.node_id) return false;
          return x < other.x + nodeWidth + 8 && x + nodeWidth + 8 > other.x
            && y < other.y + nodeHeight + 8 && y + nodeHeight + 8 > other.y;
        });
        if (collides) return;
        positions.set(node.node_id, { x, y });
        group.setAttribute("transform", `translate(${x - drag.startX} ${y - drag.startY})`);
        drawEdges();
      });
      const finishDrag = (event) => {
        if (!drag || event.pointerId !== drag.pointerId) return;
        const wasClick = event.type === "pointerup" && !drag.moved;
        drag = null;
        if (wasClick) selectPath(node);
        scheduleReturnHome();
      };
      group.addEventListener("pointerup", finishDrag);
      group.addEventListener("pointercancel", finishDrag);
      group.addEventListener("dblclick", (event) => {
        event.preventDefault();
        openNodeDetails(scenario, node);
      });
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectPath(node);
        }
      });
      nodeLayer.appendChild(group);
    });
    applyPathHighlight();
    document.getElementById("admin-overview-title").textContent = `Tổng quan · ${scenario.title}`;
    overview.replaceChildren();
    if (scenario.summary) addHtml(overview, "p", "", scenario.summary);
    const persona = scenario.persona || {};
    addHtml(overview, "p", "", `Nhân vật: ${persona.name || "—"} · Vai giả danh: ${persona.claimed_role || "—"} · Mức áp lực: ${persona.pressure_level ?? "—"}/5`);
    if (persona.speaking_style) addHtml(overview, "p", "", `Cách nói: ${persona.speaking_style}`);
    if (scenario.lesson_summary) addHtml(overview, "p", "", `Bài học: ${scenario.lesson_summary}`);
    if (scenario.red_flags?.length) {
      addHtml(overview, "h4", "", "Dấu hiệu cảnh báo");
      const list = document.createElement("ul");
      scenario.red_flags.forEach((flag) => {
        const item = document.createElement("li");
        item.textContent = `${flag.title} (${flag.severity}) — ${flag.explanation}`;
        list.appendChild(item);
      });
      overview.appendChild(list);
    }
    fitGraph();
    const scoring = scenario.scoring || {};
    if (scoring.rules?.length) {
      addHtml(overview, "h4", "", `Luật chấm điểm · Điểm ban đầu ${scoring.base_score ?? "—"}`);
      const list = document.createElement("ul");
      scoring.rules.forEach((rule) => {
        const item = document.createElement("li");
        item.textContent = `${labels[rule.intent] || rule.intent}${rule.stage_id ? ` tại ${rule.stage_id}` : ""}: ${rule.points_delta > 0 ? "+" : ""}${rule.points_delta} điểm${rule.critical ? " · nghiêm trọng" : ""} — ${rule.feedback}`;
        list.appendChild(item);
      });
      overview.appendChild(list);
    }
  }
  function selectScenario(scenario) {
    if (selectedScenarioKey === scenario.key) return;
    selectedScenarioKey = scenario.key;
    scenarioSelect.value = scenario.key;
    status.textContent = `${scenario.status} · ${scenario.nodes.length} node · ${scenario.transitions.length} nhánh`;
    drawGraph(scenario);
    overviewButton.disabled = false;
  }
  async function loadScenarios() {
    error.hidden = true;
    status.textContent = "Đang tải kịch bản…";
    try {
      const response = await fetch("/api/arena/admin/scenarios/graphs");
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Không tải được danh sách kịch bản.");
      scenarios = payload;
      scenarioSelect.replaceChildren(...scenarios.map((scenario) =>
        new Option(`${scenario.title} · ${scenario.status}`, scenario.key)
      ));
      scenarioSelect.disabled = !scenarios.length;
      if (!scenarios.length) {
        status.textContent = "Chưa có kịch bản.";
        return;
      }
      selectScenario(scenarios[0]);
    } catch (err) {
      status.textContent = "";
      error.textContent = err.message;
      error.hidden = false;
    }
  }
  document.addEventListener('arena:catalog-updated', () => {
    scenarios=[];selectedScenarioKey=null;
    if(!dialog.hidden)loadScenarios();
  });
  document.addEventListener("arena:viewchange", event => {
    if(event.detail.mode!=="scenarios")return;
    if (!scenarios.length) loadScenarios();
    else requestAnimationFrame(fitGraph);
  });
  scenarioSelect.addEventListener("change", () => {
    const scenario = scenarios.find((item) => item.key === scenarioSelect.value);
    if (scenario) selectScenario(scenario);
  });
  overviewButton.addEventListener("click", () => {
    overview.scrollTop = 0;
    overviewDialog.show();
  });
  document.getElementById("admin-overview-close").addEventListener("click", () => overviewDialog.close());
  overviewDialog.addEventListener("click", (event) => { if (event.target === overviewDialog) overviewDialog.close(); });
  document.getElementById("admin-zoom-fit").addEventListener("click", fitGraph);
  let pan = null;
  graphScroll.addEventListener("pointerdown", (event) => {
    if (pan || event.pointerType !== "mouse" || event.button !== 0 || event.target.closest(".graph-node")) return;
    const bounds = graphScroll.getBoundingClientRect();
    const x = event.clientX - bounds.left - graphScroll.clientLeft;
    const y = event.clientY - bounds.top - graphScroll.clientTop;
    if (x < 0 || y < 0 || x >= graphScroll.clientWidth || y >= graphScroll.clientHeight) return;
    event.preventDefault();
    pan = {
      pointerId: event.pointerId, x: event.clientX, y: event.clientY,
      left: graphScroll.scrollLeft, top: graphScroll.scrollTop,
    };
    graphScroll.setPointerCapture(event.pointerId);
    graphScroll.classList.add("is-panning");
  });
  graphScroll.addEventListener("pointermove", (event) => {
    if (!pan || event.pointerId !== pan.pointerId) return;
    graphScroll.scrollLeft = pan.left + pan.x - event.clientX;
    graphScroll.scrollTop = pan.top + pan.y - event.clientY;
  });
  function stopPan(event) {
    if (!pan || event.pointerId !== pan.pointerId) return;
    pan = null;
    graphScroll.classList.remove("is-panning");
  }
  graphScroll.addEventListener("pointerup", stopPan);
  graphScroll.addEventListener("pointercancel", stopPan);
  graphScroll.addEventListener("lostpointercapture", stopPan);
  graphScroll.addEventListener("wheel", (event) => {
    event.preventDefault();
    const bounds = graphScroll.getBoundingClientRect();
    setZoom(mapZoom * (event.deltaY < 0 ? 1.1 : 1 / 1.1), event.clientX - bounds.left, event.clientY - bounds.top);
  }, { passive: false });
  document.getElementById("admin-lines-close").addEventListener("click", () => linesDialog.close());
  linesDialog.addEventListener("click", (event) => { if (event.target === linesDialog) linesDialog.close(); });
})();
