(async () => {
  'use strict';
  const $=id=>document.getElementById(id), E=PracticeEditor;
  let catalog=[],drafts=[],doc=null,draftInfo=null,sourceId=null,dirty=false,jsonDirty=false,editRevision=0,generation=0,trial=null,trialDoc=null;
  const actions={none:'Không yêu cầu',other:'Trao đổi / xác nhận thông tin thông thường',share_sensitive:'Yêu cầu mã hoặc thông tin nhạy cảm',transfer_money:'Yêu cầu chuyển tiền',install_app:'Yêu cầu cài ứng dụng',click_link:'Yêu cầu mở đường dẫn',share_screen:'Yêu cầu chia sẻ màn hình',keep_secret:'Yêu cầu giữ bí mật'};
  const paths={title:['title'],family:['family'],kind:['scenario_kind'],difficulty:['difficulty'],summary:['summary'],context:['user_context'],speaking:['persona','speaking_style'],'persona-name':['persona','name'],'persona-role':['persona','claimed_role'],pressure:['persona','pressure_level'],lesson:['lesson_summary'],'base-score':['scoring','base_score']};
  function node(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
  function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
  async function api(path,body){const r=await fetch('/api/practice/admin/'+path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;}
  async function perform(button,fn){button.disabled=true;try{await fn();}catch(e){status(e.message,true);}finally{button.disabled=false;}}
  function state(){ $('editor-title').textContent=doc?.title||'Kịch bản chưa đặt tên';$('editor-state').textContent=(dirty?'Có thay đổi chưa lưu':'Đã tải / lưu')+(draftInfo?' · Bản nháp #'+draftInfo.draft_id:'')+(sourceId?' · Đang chỉnh bản mới':' · Chưa phát hành');}
  function changed(){dirty=true;editRevision++;state();}
  function mayReplace(){return (!dirty&&!jsonDirty)||confirm('Nội dung chưa lưu. Bạn muốn bỏ thay đổi để mở kịch bản khác?');}
  function tab(name){document.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.id!==name);document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tab===name)));}
  document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
  function field(label,value,set,{type='text',options=null,wide=false,placeholder=''}={}){
    const wrap=node('label',wide?'wide':'',label);const input=node(options?'select':type==='textarea'?'textarea':'input');
    if(options){for(const [key,caption] of options)input.add(new Option(caption,key));}
    else if(type!=='textarea')input.type=type;
    input.setAttribute('aria-label',label);
    input.value=value??'';if(placeholder)input.placeholder=placeholder;
    input.addEventListener(options?'change':'input',()=>{set(type==='number'?Number(input.value):input.value);changed();});wrap.append(input);return wrap;
  }
  function button(text,fn,cls=''){const b=node('button',cls,text);b.type='button';b.onclick=fn;return b;}
  function destinations(includeAll=false){return (includeAll?[['','Áp dụng cho mọi bước']]:[]).concat(doc.stages.map((s,i)=>[s.id,`Bước ${i+1} · ${s.opening_line.slice(0,38)||s.id}`]),Object.entries(E.terminals));}
  function stagesOnly(all=false){return destinations(all).filter(([id])=>!E.terminals[id]);}
  function renderStages(){
    $('start').replaceChildren(...stagesOnly().map(([id,label])=>new Option(label,id)));$('start').value=doc.start_stage_id;
    $('stages').replaceChildren();
    doc.stages.forEach((s,i)=>{
      const card=node('details','stage-card');card.open=i===0;
      const heading=node('summary');heading.append(node('span','stage-badge',`BƯỚC ${i+1}`),node('span','stage-title',s.opening_line.slice(0,80)||'Chưa có lời mở đầu'));card.append(heading);
      const tools=node('div','card-toolbar');tools.append(button('Xóa bước',()=>{
        if(doc.stages.length===1){status('Cần giữ ít nhất một bước.',true);return;}
        const refs=E.references(doc,s.id);if(doc.start_stage_id===s.id)refs.unshift('bước mở đầu');
        if(refs.length){status('Chưa thể xóa: '+refs.join(', ')+' đang dùng bước này. Hãy đổi đích đến trước.',true);return;}
        doc.stages.splice(i,1);changed();renderStages();renderFlags();renderRules();
      },'danger'));card.append(tools);
      const fields=node('div','fields');
      fields.append(field('Lời người gọi ở bước này',s.opening_line,v=>{s.opening_line=v;heading.querySelector('.stage-title').textContent=v.slice(0,80)||'Chưa có lời mở đầu';},{type:'textarea',wide:true}),
        field('Mục tiêu của bước',s.objective,v=>s.objective=v,{type:'textarea',wide:true}),
        field('Hành động người gọi yêu cầu',s.requested_action,v=>s.requested_action=v,{options:Object.entries(actions)}),
        field('Số lượt tối đa ở bước này',s.max_turns,v=>s.max_turns=v,{type:'number'}),
        field('Câu hỏi lại khi chưa rõ (mỗi dòng một câu)',s.fallback_lines.join('\n'),v=>s.fallback_lines=v.split('\n').map(x=>x.trim()).filter(Boolean),{type:'textarea',wide:true}),
        field('Cách gây áp lực / chiến thuật (mỗi dòng một ý)',s.tactics.join('\n'),v=>s.tactics=v.split('\n').map(x=>x.trim()).filter(Boolean),{type:'textarea',wide:true}));
      card.append(fields,node('p','hint','Nếu người chơi phản ứng như sau, chuyển đến:'));
      const transitions=node('div','transition-grid');
      for(const [intent,label] of Object.entries(E.intents)){
        const edge=s.transitions.find(t=>t.on_intent===intent);
        transitions.append(field(label,edge?.next_stage_id||'',value=>{
          const old=s.transitions.find(t=>t.on_intent===intent);s.transitions=s.transitions.filter(t=>t.on_intent!==intent);
          if(value)s.transitions.push({...old,on_intent:intent,next_stage_id:value});
        },{options:[['','Chưa có nhánh riêng · hỏi lại / dự phòng'],...destinations()]}));
      }
      card.append(transitions);
      const more=node('details');more.append(node('summary','','Cấu hình dự phòng của bước'));
      more.append(field('Đích dự phòng',s.default_next_stage_id,v=>s.default_next_stage_id=v,{options:destinations()}),field('Khi hết số lượt ở bước này',s.timeout_next_stage_id,v=>s.timeout_next_stage_id=v,{options:destinations()}),node('p','hint','Mã bước: '+s.id));card.append(more);$('stages').append(card);
    });
  }
  function renderFlags(){
    $('flags').replaceChildren();if(!doc.red_flags.length)$('flags').append(node('p','hint','Chưa có dấu hiệu. Bắt buộc bổ sung nếu đây là cuộc gọi giả mạo.'));
    doc.red_flags.forEach((f,i)=>{
      const card=node('div','flag-card'),fields=node('div','fields');
      fields.append(field('Tên dấu hiệu',f.title,v=>f.title=v),field('Xuất hiện ở bước',f.stage_id,v=>f.stage_id=v,{options:stagesOnly()}),field('Giải thích cho người chơi',f.explanation,v=>f.explanation=v,{type:'textarea',wide:true}),field('Mức độ',f.severity,v=>f.severity=v,{options:[['low','Thấp'],['medium','Trung bình'],['high','Cao']]}));
      card.append(fields,button('Xóa dấu hiệu',()=>{doc.red_flags.splice(i,1);changed();renderFlags();},'danger'));$('flags').append(card);
    });
  }
  function renderRules(){
    $('rules').replaceChildren();doc.scoring.rules.forEach((r,i)=>{
      const card=node('div','rule-card'),fields=node('div','fields');
      fields.append(field('Phản ứng',r.intent,v=>r.intent=v,{options:Object.entries(E.intents)}),field('Ở bước',r.stage_id||'',v=>r.stage_id=v||null,{options:stagesOnly(true)}),field('Điểm cộng / trừ',r.points_delta,v=>r.points_delta=v,{type:'number'}),field('Nhận xét',r.feedback,v=>r.feedback=v,{type:'textarea',wide:true}));
      const critical=node('label','inline');const check=node('input');check.type='checkbox';check.checked=r.critical;check.onchange=()=>{r.critical=check.checked;changed();};critical.append(check,document.createTextNode('Đánh dấu hành động rủi ro nghiêm trọng'));
      card.append(fields,critical,button('Xóa luật điểm',()=>{doc.scoring.rules.splice(i,1);changed();renderRules();},'danger'));$('rules').append(card);
    });
  }
  function snapshot(){
    if(jsonDirty)throw Error('JSON đang có thay đổi chưa áp dụng. Bấm “Áp dụng JSON vào form” trước.');
    const copy=E.clone(doc);copy.status='published';copy.updated_at=new Date().toISOString();copy.published_at=copy.published_at||copy.updated_at;
    copy.stages.forEach(s=>{if(!s.fallback_lines.length)s.fallback_lines=[s.opening_line];});return copy;
  }
  function loadDocument(value,{draft=null,editing=false}={}){
    generation++;doc=E.clone(value);draftInfo=draft;dirty=false;jsonDirty=false;editRevision=0;
    const row=catalog.find(r=>r.document.id===doc.id);sourceId=row?.scenario_id||null;
    if(editing)doc.version=Math.max(doc.version,row?.document.version||0)+1;
    for(const [id,path] of Object.entries(paths)){
      const obj=path.length===2?doc[path[0]]:doc,key=path.at(-1);$(id).value=obj[key]??'';
      $(id).oninput=()=>{obj[key]=['pressure','base-score'].includes(id)?Number($(id).value):$(id).value;changed();};
    }
    for(const key of ['evidence','official']){
      $(key).value=doc.case_blueprint?.[key]||'';$(key).oninput=()=>{doc.case_blueprint||={evidence:'',official:''};doc.case_blueprint[key]=$(key).value;changed();};
    }
    $('scenario-id').value=doc.id;$('document').value=JSON.stringify(doc,null,2);$('json-state').textContent='';
    $('enabled').checked=row?.status==='published';$('weight').value=row?.selection_weight||1;$('selection').disabled=!sourceId;
    if(row)$('catalog').value=String(row.scenario_id);else $('catalog').value='';
    renderStages();renderFlags();renderRules();state();tab('editor');
  }
  $('editor-form').addEventListener('submit',event=>event.preventDefault());
  $('start').onchange=()=>{doc.start_stage_id=$('start').value;changed();};
  $('new').onclick=()=>{if(mayReplace()){loadDocument(E.fresh());changed();status('Kịch bản mới chưa phát hành. Điền bối cảnh, bằng chứng, lời thoại và bài học.');}};
  $('clone').onclick=()=>{try{const copy=E.duplicate(snapshot());loadDocument(copy);changed();status('Đã nhân bản với mã riêng; chưa phát hành.');}catch(e){status(e.message,true);}};
  $('catalog').onchange=()=>{const row=catalog.find(r=>String(r.scenario_id)===$('catalog').value);if(!row)return;if(!mayReplace()){$('catalog').value=sourceId?String(sourceId):'';return;}loadDocument(row.document,{editing:true});status('Đang sửa một phiên bản mới; bản người chơi đang dùng chưa thay đổi.');};
  $('add-stage').onclick=()=>{if(doc.stages.length>=30){status('Tối đa 30 bước.',true);return;}const s=E.stage('step-'+crypto.randomUUID().slice(0,8));doc.stages.push(s);changed();renderStages();renderFlags();renderRules();$('stages').lastElementChild.open=true;status('Đã thêm bước. Hãy nối một phản ứng ở bước trước tới bước mới.');};
  $('add-flag').onclick=()=>{doc.red_flags.push({id:'flag-'+crypto.randomUUID().slice(0,8),stage_id:doc.start_stage_id,title:'',explanation:'',severity:'high'});changed();renderFlags();};
  $('add-rule').onclick=()=>{doc.scoring.rules.push({intent:'unknown',stage_id:null,points_delta:0,feedback:'',critical:false});changed();renderRules();};
  $('document').oninput=()=>{jsonDirty=true;$('json-state').textContent='Có thay đổi JSON chưa áp dụng vào form.';};
  $('json-export').onclick=()=>{if(jsonDirty&&!confirm('Ghi đè JSON chưa áp dụng bằng dữ liệu từ form?'))return;jsonDirty=false;$('document').value=JSON.stringify(snapshot(),null,2);$('json-state').textContent='JSON đã cập nhật từ form.';};
  $('json-panel').addEventListener('toggle',()=>{if($('json-panel').open&&!jsonDirty)$('document').value=JSON.stringify(snapshot(),null,2);});
  $('json-apply').onclick=()=>perform($('json-apply'),async()=>{const data=await api('validate',{document:JSON.parse($('document').value)});const savedDraft=draftInfo;loadDocument(data.document,{draft:savedDraft});changed();status('Đã áp dụng JSON hợp lệ vào form. Chưa phát hành.');});
  async function loadCatalog(){catalog=await api('catalog');$('catalog').replaceChildren(new Option('Chọn kịch bản đã phát hành…',''),...catalog.map(r=>new Option(`${r.document.title} · bản ${r.revision}`,String(r.scenario_id))));if(sourceId)$('catalog').value=String(sourceId);}
  async function loadDrafts(){
    drafts=await api('drafts');$('draft-list').replaceChildren();
    if(!drafts.length)$('draft-list').append(node('p','hint','Bạn chưa lưu bản nháp nào.'));
    drafts.forEach(d=>{const card=node('article','list-card');card.append(node('h3','',d.document.title||'Chưa đặt tên'),node('p','hint',`#${d.draft_id} · Lưu ${new Date(d.updated_at).toLocaleString('vi-VN')}`),button('Tiếp tục soạn',()=>{if(mayReplace()){loadDocument(d.document,{draft:d});status('Đã mở bản nháp riêng của bạn.');}}));$('draft-list').append(card);});
  }
  $('save-draft').onclick=()=>perform($('save-draft'),async()=>{
    const body={document:snapshot(),draft_id:draftInfo?.draft_id||null,expected_revision:draftInfo?.revision||null};const gen=generation,rev=editRevision;
    const saved=await api('drafts',body);if(gen===generation){draftInfo=saved;if(rev===editRevision)dirty=false;state();}await loadDrafts();status('Đã lưu nháp trên máy chủ. Chưa phát hành cho người chơi.');
  });
  async function loadReviews(){
    const rows=await api('reviews');$('review-list').replaceChildren();if(!rows.length)$('review-list').append(node('p','hint','Chưa có đề xuất.'));
    rows.forEach(r=>{
      const card=node('article','list-card');card.append(node('h3','',`#${r.review_id} · ${r.document.title}`),node('p','hint',`${({pending:'Chờ duyệt',approved:'Đã phát hành',rejected:'Đã từ chối'})[r.status]} · ${r.document.stages.length} bước · ${r.document.scenario_kind==='benign'?'Bình thường':'Giả mạo'}`),node('p','',r.document.user_context));
      const readable=node('details');readable.append(node('summary','','Xem lời thoại và các nhánh'));
      r.document.stages.forEach((s,i)=>{
        readable.append(node('h3','',`Bước ${i+1} · ${s.id}`),node('p','',s.opening_line));
        const list=node('ul');s.transitions.forEach(t=>list.append(node('li','',`${E.intents[t.on_intent]||t.on_intent} → ${E.terminals[t.next_stage_id]||'Bước '+(r.document.stages.findIndex(x=>x.id===t.next_stage_id)+1)}`)));readable.append(list);
      });card.append(readable);
      const details=node('details');details.append(node('summary','','Xem toàn bộ cấu hình đề xuất'),node('pre','',JSON.stringify(r.document,null,2)));card.append(details);
      if(r.status==='pending')for(const [decision,label] of [['approve','Duyệt phát hành'],['reject','Từ chối']]){const b=button(label,()=>perform(b,async()=>{await api(`reviews/${r.review_id}/${decision}`,{});if(decision==='approve'&&parent!==window)parent.postMessage({type:'arena:catalog-updated'},location.origin);await Promise.all([loadCatalog(),loadReviews()]);status(decision==='approve'?'Đã phát hành phiên bản mới. Cuộc gọi cũ giữ phiên bản cũ.':'Đã từ chối đề xuất.');}));card.append(b);}
      $('review-list').append(card);
    });
  }
  $('submit').onclick=()=>perform($('submit'),async()=>{const data=snapshot(),gen=generation,rev=editRevision;await api('reviews',{document:data});if(gen===generation&&rev===editRevision){dirty=false;state();}await loadReviews();tab('reviews');status('Đã kiểm tra cấu trúc và gửi vào hàng đợi. Chỉ đưa vào sử dụng sau khi bấm Duyệt phát hành.');});
  $('reviews-refresh').onclick=()=>perform($('reviews-refresh'),loadReviews);
  $('selection').onclick=()=>perform($('selection'),async()=>{if(!sourceId)throw Error('Cần phát hành kịch bản trước khi chỉnh tần suất.');await api(`catalog/${sourceId}/selection`,{enabled:$('enabled').checked,weight:Number($('weight').value)});await loadCatalog();status('Đã lưu tần suất của bản đang phát hành.');});
  async function loadReport(){const r=await api('report');$('stat-cards').replaceChildren();for(const [label,value] of [['Đã đánh giá',r.total],['Nhận định đúng',r.correct],['Nghi ngờ nhầm',r.false_alarms],['Bỏ sót giả mạo',r.missed_frauds],['Chưa kết luận',r.uncertain]]){const card=node('div','stat');card.append(node('strong','',String(value)),node('span','',label));$('stat-cards').append(card);}$('report').textContent=JSON.stringify(r,null,2);}
  $('refresh').onclick=()=>perform($('refresh'),loadReport);
  function trialLine(text,player=false){const p=node('p',player?'player':'',text.replaceAll('{reference}','DEMO-TEST').replaceAll('{window}','chiều nay').replaceAll('{place}','sảnh tòa nhà'));$('preview-log').append(p);$('preview-log').scrollTop=$('preview-log').scrollHeight;}
  function trialStep(){
    $('preview-choices').replaceChildren();if(trial.ended){trialLine(E.terminals[trial.current]);return;}
    const s=trialDoc.stages.find(s=>s.id===trial.current);trialLine(s.opening_line);
    for(const [intent,label] of Object.entries(E.intents))$('preview-choices').append(button(label,()=>{trialLine(label,true);trial=E.preview(trialDoc,trial.current,intent,trial.visits,trial.count,trial.unknown);trialStep();}));
  }
  function resetTrial(){$('preview-log').replaceChildren();trial={current:trialDoc.start_stage_id,visits:{},count:0,unknown:0,ended:false};trialStep();}
  $('preview-open').onclick=()=>perform($('preview-open'),async()=>{const r=await api('validate',{document:snapshot()});trialDoc=r.document;resetTrial();$('preview').showModal();});
  $('preview-close').onclick=()=>$('preview').close();$('preview-reset').onclick=resetTrial;
  window.addEventListener('beforeunload',event=>{if(dirty||jsonDirty){event.preventDefault();event.returnValue='';}});
  try{await Promise.all([loadCatalog(),loadDrafts(),loadReviews(),loadReport()]);loadDocument(catalog[0]?.document||E.fresh(),{editing:Boolean(catalog.length)});$('content').hidden=false;status('Quyền quản trị đã được xác nhận. Chọn kịch bản hoặc tạo mới để bắt đầu.');}
  catch(e){status('Chưa truy cập được: '+e.message,true);}
})();
