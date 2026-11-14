"""Generate a browser-based flowchart for the scenario JSON files."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = ROOT / "data" / "scenarios"
OUTPUT = ROOT / "frontend" / "static" / "scenario-map.html"


def _load_scenarios() -> list[dict[str, Any]]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        try:
            scenario = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Không đọc được {path.name}: {exc}") from exc
        if not isinstance(scenario.get("stages"), list):
            raise ValueError(f"{path.name} không có danh sách stages hợp lệ.")
        scenario["source_file"] = path.name
        scenarios.append(scenario)
    if not scenarios:
        raise ValueError(f"Không tìm thấy file JSON trong {SCENARIOS_DIR}.")
    return scenarios


def _page(scenarios: list[dict[str, Any]]) -> str:
    data = json.dumps(scenarios, ensure_ascii=False, separators=(",", ":"))
    # Prevent user-authored scenario text from terminating the JSON script tag.
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    return _HTML.replace("__SCENARIO_DATA__", data).replace("__GENERATED_AT__", html.escape(generated_at))


def generate_scenario_map(output: Path = OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_page(_load_scenarios()), encoding="utf-8")
    return output


_HTML = r'''<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scam Arena — Sơ đồ kịch bản</title>
  <style>
    :root{font-family:Segoe UI,Arial,sans-serif;color:#193029;background:#f2f5f0;--green:#126348;--muted:#6f8179;--line:#dfe8e1}
    *{box-sizing:border-box}body{margin:0}.shell{max-width:1200px;margin:28px auto;padding:0 20px}
    header{display:flex;justify-content:space-between;gap:18px;align-items:end;margin-bottom:20px}h1{font-size:25px;margin:0 0 6px}.subtitle,.meta{color:var(--muted);font-size:13px;margin:0}
    .controls,.diagram-panel{background:white;border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:16px}
    .controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap}.field{display:grid;gap:6px;font-size:12px;font-weight:700}.field select{min-width:190px;padding:10px;border:1px solid #d8e2da;border-radius:9px;background:#fff;font:14px inherit;color:#193029}
    button{padding:10px 14px;border:0;border-radius:9px;background:var(--green);color:white;font-weight:700;cursor:pointer}button.secondary{background:#edf4ef;color:#27513d;border:1px solid #dce9df}
    .legend{font-size:12px;color:var(--muted);margin-left:auto}.diagram-wrap{width:100%;overflow:auto;min-height:260px}.diagram svg{max-width:none;height:auto}.error{color:#a53f2e;padding:12px}.node-info{font-size:12px;color:var(--muted)}
    @media(max-width:700px){header{display:block}.legend{margin-left:0;width:100%}.field{flex:1}.field select{min-width:0;width:100%}}
  </style>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
</head>
<body>
<main class="shell">
  <header><div><h1>Sơ đồ kịch bản Scam Arena</h1><p class="subtitle">Tạo từ JSON kịch bản. Sửa JSON rồi chạy lại lệnh sinh sơ đồ để cập nhật.</p></div><p class="meta">Sinh lúc __GENERATED_AT__</p></header>
  <section class="controls">
    <label class="field">Kịch bản<select id="scenario"></select></label>
    <label class="field">Giai đoạn<select id="stage"><option value="*">Tất cả giai đoạn</option></select></label>
    <button id="copy" class="secondary" type="button">Sao chép mã Mermaid</button>
    <button id="download" class="secondary" type="button">Tải SVG</button>
    <span class="legend">Mũi tên liền: ý định · nét đứt: mặc định / hết lượt · màu xanh: an toàn · đỏ: rủi ro</span>
  </section>
  <section class="diagram-panel"><div id="diagram" class="diagram-wrap" aria-live="polite"></div><p id="error" class="error" hidden></p><p id="node-info" class="node-info"></p></section>
</main>
<script id="scenario-data" type="application/json">__SCENARIO_DATA__</script>
<script>
(() => {
  const scenarios = JSON.parse(document.getElementById("scenario-data").textContent);
  const scenarioSelect = document.getElementById("scenario");
  const stageSelect = document.getElementById("stage");
  const output = document.getElementById("diagram");
  const error = document.getElementById("error");
  const info = document.getElementById("node-info");
  let lastSvg = "";
  let renderNo = 0;
  const terminalInfo = {
    END_SAFE: {id:"terminalSafe", label:"Kết thúc an toàn", style:"safe"},
    END_UNSAFE: {id:"terminalRisk", label:"Kết thúc rủi ro", style:"risk"},
    END_NEUTRAL: {id:"terminalNeutral", label:"Kết thúc · chưa đủ dữ liệu", style:"neutral"},
  };
  const text = (value) => String(value ?? "").replace(/[\r\n\t]+/g," ").replace(/\s+/g," ").replace(/"/g,"”").trim();
  const short = (value, max=92) => { const s=text(value); return s.length>max ? s.slice(0,max-1)+"…" : s; };
  const stageNodeId = (index) => `stage${index}`;

  scenarios.forEach((scenario, index) => {
    const option = document.createElement("option");
    option.value=String(index); option.textContent=`${scenario.title || scenario.id} (${scenario.id})`;
    scenarioSelect.appendChild(option);
  });

  function populateStages() {
    const scenario=scenarios[Number(scenarioSelect.value)];
    stageSelect.replaceChildren();
    const all=document.createElement("option"); all.value="*"; all.textContent="Tất cả giai đoạn"; stageSelect.appendChild(all);
    (scenario.stages || []).forEach((stage,index) => {
      const option=document.createElement("option");
      option.value=String(index); option.textContent=`${stage.id} — ${stage.objective || ""}`;
      stageSelect.appendChild(option);
    });
  }

  function makeGraph(scenario, selectedStage) {
    const stages=scenario.stages || [];
    const stageIds=new Map(stages.map((stage,index)=>[stage.id,index]));
    const edges=[]; const used=new Set(); const terminalUsed=new Set();
    const mapTarget=(key) => {
      if(stageIds.has(key)) { const id=stageNodeId(stageIds.get(key)); used.add(id); return id; }
      if(terminalInfo[key]) { terminalUsed.add(key); return terminalInfo[key].id; }
      const ghost=`missing${String(key).replace(/[^A-Za-z0-9]/g,"") || "Node"}`; used.add(ghost); return ghost;
    };
    stages.forEach((stage,index)=>{
      if(selectedStage!=="*" && Number(selectedStage)!==index) return;
      const from=stageNodeId(index); used.add(from);
      (stage.transitions || []).forEach((transition)=>{
        const to=mapTarget(transition.next_stage_id);
        edges.push(`${from} -->|${text(transition.on_intent)}| ${to}`);
      });
      if(stage.default_next_stage_id) {
        const to=mapTarget(stage.default_next_stage_id);
        edges.push(`${from} -.->|Mặc định| ${to}`);
      }
      if(stage.timeout_next_stage_id) {
        const to=mapTarget(stage.timeout_next_stage_id);
        edges.push(`${from} -.->|Hết lượt| ${to}`);
      }
    });
    if(!edges.length) return "flowchart LR\n  empty[Chưa có nhánh trong giai đoạn này]";
    const lines=["flowchart LR"];
    stages.forEach((stage,index)=>{
      const id=stageNodeId(index);
      if(!used.has(id)) return;
      const label=`${stage.id}: ${short(stage.opening_line || stage.objective || "")}`;
      lines.push(`  ${id}["${label}"]`);
    });
    for(const key of terminalUsed) {
      const term=terminalInfo[key];
      lines.push(`  ${term.id}(["${term.label}"])`);
    }
    for(const id of used) {
      if(id.startsWith("missing")) lines.push(`  ${id}["Đích chưa tồn tại: ${id.slice(7)}"]`);
    }
    lines.push(...edges.map(edge=>`  ${edge}`));
    const start=stages.findIndex(stage=>stage.id===scenario.start_stage_id);
    if(start>=0 && used.has(stageNodeId(start))) lines.push(`  class ${stageNodeId(start)} startNode`);
    lines.push("  classDef startNode fill:#e7f3eb,stroke:#126348,stroke-width:3px");
    lines.push("  classDef safe fill:#e7f3eb,stroke:#126348,stroke-width:2px");
    lines.push("  classDef risk fill:#fff0ec,stroke:#c64d39,stroke-width:2px");
    lines.push("  classDef neutral fill:#f2f3f4,stroke:#748179,stroke-width:2px");
    if(terminalUsed.has("END_SAFE")) lines.push("  class terminalSafe safe");
    if(terminalUsed.has("END_UNSAFE")) lines.push("  class terminalRisk risk");
    if(terminalUsed.has("END_NEUTRAL")) lines.push("  class terminalNeutral neutral");
    return lines.join("\n");
  }

  async function render() {
    error.hidden=true; output.replaceChildren();
    const scenario=scenarios[Number(scenarioSelect.value)];
    const source=makeGraph(scenario,stageSelect.value);
    info.textContent=`${scenario.stages.length} giai đoạn · ${(scenario.stages || []).reduce((sum,s)=>sum+(s.transitions || []).length,0)} nhánh intent · nguồn ${scenario.source_file}`;
    if(!window.mermaid) { error.textContent="Không tải được thư viện Mermaid. Kiểm tra kết nối Internet rồi tải lại trang."; error.hidden=false; return; }
    try {
      const result=await mermaid.render(`scenarioGraph${++renderNo}`,source);
      lastSvg=result.svg; output.innerHTML=result.svg; result.bindFunctions?.(output);
    } catch(err) { error.textContent=`Không vẽ được sơ đồ: ${err.message}`; error.hidden=false; }
  }

  scenarioSelect.addEventListener("change",()=>{populateStages();render();});
  stageSelect.addEventListener("change",render);
  document.getElementById("copy").addEventListener("click",async()=>{
    try { await navigator.clipboard.writeText(makeGraph(scenarios[Number(scenarioSelect.value)],stageSelect.value)); info.textContent="Đã sao chép mã Mermaid."; }
    catch { info.textContent="Trình duyệt chặn clipboard; hãy mở rộng sơ đồ bằng Mermaid Live Editor nếu cần."; }
  });
  document.getElementById("download").addEventListener("click",()=>{
    if(!lastSvg) return;
    const blob=new Blob([lastSvg],{type:"image/svg+xml;charset=utf-8"});
    const url=URL.createObjectURL(blob); const link=document.createElement("a");
    link.href=url; link.download=`${scenarios[Number(scenarioSelect.value)].id}-scenario.svg`;
    link.click(); URL.revokeObjectURL(url);
  });
  window.mermaid?.initialize({startOnLoad:false,securityLevel:"strict",theme:"neutral",flowchart:{curve:"basis",htmlLabels:false}});
  populateStages(); render();
})();
</script>
</body>
</html>'''


if __name__ == "__main__":
    print(f"Generated scenario map: {generate_scenario_map()}")
