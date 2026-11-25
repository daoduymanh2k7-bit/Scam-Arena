(() => {
  const screen=document.getElementById('data-review-screen');
  if(!screen)return;
  const list=screen.querySelector('[data-review-list]');
  const status=screen.querySelector('[data-review-status]');
  const filter=screen.querySelector('[data-review-filter]');
  const kind=screen.querySelector('[data-review-kind]');
  const run=screen.querySelector('[data-review-run]');
  const labels={verify:'Tự xác minh',refuse:'Từ chối',doubt:'Nghi ngờ / phủ nhận',comply:'Đồng ý',
    share_sensitive:'Cung cấp thông tin',transfer_money:'Chuyển tiền',hang_up:'Kết thúc',unknown:'Chưa rõ / bỏ mẫu'};
  const kinds={intent:'Câu cần duyệt',rule:'Luật nhận diện',stale_session:'Phiên bỏ dở',duplicate:'Mục trùng',dialogue:'Lời thoại lệch bước'};
  let page=1,timer=null,generation=0,lastItems='';
  const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const button=(text)=>{const b=el('button',text,'users-button');b.type='button';return b;};
  async function api(path='',body){
    const response=await fetch('/api/admin/data-review'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Chưa thực hiện được thao tác.');return data;
  }
  function paragraph(parent,title,value){if(!value)return;const p=el('p');p.append(el('strong',title+' '),el('span',value));parent.append(p);}
  function card(item){
    const details=el('details',undefined,'data-review-row');
    const summary=el('summary');
    summary.append(el('span',kinds[item.kind],'review-kind'),el('span',
      item.original.player_text||item.original.phrase||item.original.bot_reply_text||
      (item.kind==='duplicate'?`${item.original.candidate_ids?.length||item.original.sample_ids?.length} mục trùng`:'Phiên không có hoạt động hơn 24 giờ'),'review-preview'),
      el('span',item.decision==='pending'?({ready:'Chờ duyệt',pending:'Chờ phân tích',failed:'Phân tích lỗi',not_configured:'Chưa cấu hình LLM'}[item.analysis_status]):item.decision==='accepted'?'Đã chấp nhận':'Đã bỏ qua','review-state'));
    details.append(summary);
    const content=el('div',undefined,'review-details');details.append(content);
    const original=item.original,suggestion=item.suggestion;
    paragraph(content,'Tình huống:',original.scenario_title);
    for(const turn of original.recent_turns||[]){paragraph(content,'Người chơi trước đó:',turn.player_text);paragraph(content,'Người gọi trước đó:',turn.caller_text);}
    paragraph(content,'Người gọi:',original.caller_text);
    paragraph(content,'Câu gốc:',original.player_text||original.phrase);
    paragraph(content,'Nhãn hiện tại:',labels[original.detected_intent||original.intent]);
    if(item.kind==='stale_session'){
      paragraph(content,'Hoạt động cuối:',new Date(original.last_activity).toLocaleString('vi-VN'));
      paragraph(content,'Phiên:',`${original.interaction_mode==='call'?'Cuộc gọi':'Nhắn tin'} · ${original.turn_no} lượt`);
    }
    paragraph(content,'Lý do:',suggestion.rationale);
    if(suggestion.provider)paragraph(content,'LLM:',`${suggestion.provider} · ${suggestion.model} · ${suggestion.prompt_version}`);
    if(typeof suggestion.confidence==='number')paragraph(content,'Tự đánh giá của LLM:',`${Math.round(suggestion.confidence*100)}% — không phải độ chính xác đã kiểm chứng.`);
    if(suggestion.needs_audio)paragraph(content,'Cần kiểm tra:', 'Có thể nghe nhầm hoặc thiếu ngữ cảnh. Không có bản ghi âm đối chiếu trong lịch sử cuộc gọi.');
    if(item.kind==='dialogue')paragraph(content,'Thao tác:', 'Chấp nhận để ghi nhận đã rà soát; không sửa hay xóa lời thoại lịch sử.');
    if(original.dataset_only)paragraph(content,'Tập mẫu Rasa:',`${original.sample_ids.length} mẫu · nhãn: ${original.labels.join(', ')}. Chỉ ghi nhận cảnh báo.`);
    if(item.decision!=='pending'){
      paragraph(content,'Đã xử lý lúc:',new Date(item.reviewed_at).toLocaleString('vi-VN'));
      paragraph(content,'Nhãn đã duyệt:',labels[item.result?.intent]);paragraph(content,'Bản hiệu chỉnh:',item.result?.corrected_text);
      paragraph(content,'Ghi chú:',item.result?.note);return details;
    }
    const form=el('form',undefined,'review-decision-form');content.append(form);
    let intent=null,corrected=null;
    if(['intent','rule'].includes(item.kind)){
      const label=el('label','Nhãn sau khi duyệt');intent=el('select');intent.name='intent';
      for(const [value,text] of Object.entries(labels)){if(item.kind==='rule'&&value==='unknown')continue;const option=el('option',text);option.value=value;intent.append(option);}
      intent.value=suggestion.intent||original.intent||'unknown';label.append(intent);form.append(label);
      if(item.kind==='intent'){
        const label=el('label','Bản hiệu chỉnh — giữ nguyên ý, không ghi đè câu gốc');corrected=el('textarea');corrected.name='corrected_text';corrected.maxLength=2000;corrected.rows=2;
        corrected.value=suggestion.corrected_text||original.player_text;label.append(corrected);form.append(label);
      }
    }
    const noteLabel=el('label','Ghi chú của admin');const note=el('input');note.name='note';note.maxLength=1000;noteLabel.append(note);form.append(noteLabel);
    const actions=el('div',undefined,'review-actions');const accept=button(item.kind==='dialogue'||original.dataset_only?'Ghi nhận đã rà soát':'Chấp nhận / lưu chỉnh sửa');
    accept.disabled=item.analysis_status!=='ready';const reject=button('Bỏ qua');const feedback=el('p',undefined,'review-feedback');feedback.setAttribute('role','status');
    actions.append(accept,reject);form.append(actions,feedback);
    form.onsubmit=e=>e.preventDefault();
    const decide=async decision=>{
      accept.disabled=true;reject.disabled=true;
      try{
        await api(`/items/${item.item_id}/decision`,{decision,expected_hash:item.source_hash,
          intent:intent?.value||null,corrected_text:corrected?.value??null,note:note.value});
        document.activeElement?.blur();lastItems='';await refresh(true);
      }catch(error){feedback.textContent=error.message;accept.disabled=item.analysis_status!=='ready';reject.disabled=false;}
    };
    accept.onclick=()=>decide('accepted');reject.onclick=()=>decide('rejected');
    return details;
  }
  async function refresh(force=false){
    const current=++generation;
    try{
      const data=await api(`?decision=${filter.value}&kind=${kind.value}&page=${page}`);if(current!==generation||screen.hidden)return;
      const running=data.run?.status==='running'&&!data.run.stale;run.disabled=running;
      const counts=data.counts.map(row=>`${{pending:'Chờ duyệt',accepted:'Đã chấp nhận',rejected:'Đã bỏ qua'}[row.decision]}: ${row.n}`).join(' · ');
      status.textContent=(data.llm_configured?'Dùng cấu hình LLM nhắn tin. ':'Chưa cấu hình LLM nhắn tin. ')+
        (running?'Bot đang quét/phân tích nền… ':data.run?.status==='failed'||(data.run?.status==='running'&&data.run.stale)?'Đợt trước bị gián đoạn; có thể chạy lại. ':data.run?'Đợt gần nhất đã xong. ':'')+
        counts+(data.run?.stats?` · LLM đã phân tích: ${data.run.stats.analyzed||0}; lỗi: ${data.run.stats.failed||0}.`:'');
      const signature=JSON.stringify(data.items);
      if(signature!==lastItems&&(force||!list.contains(document.activeElement))){
        list.replaceChildren(...data.items.map(card));if(!data.items.length)list.append(el('p','Chưa có đề xuất trong mục này. Bấm Quét dữ liệu để bắt đầu.'));
        lastItems=signature;
      }
      screen.querySelector('[data-review-page]').textContent=`Trang ${page} · ${data.total} đề xuất`;
      screen.querySelector('[data-review-prev]').disabled=page<=1;
      screen.querySelector('[data-review-next]').disabled=page*20>=data.total;
      clearTimeout(timer);if(running)timer=setTimeout(refresh,3000);
    }catch(error){if(current===generation)status.textContent=error.message;}
  }
  screen.querySelector('[data-review-refresh]').onclick=()=>{lastItems='';refresh(true);};
  filter.onchange=()=>{page=1;lastItems='';refresh(true);};
  kind.onchange=()=>{page=1;lastItems='';refresh(true);};
  screen.querySelector('[data-review-prev]').onclick=()=>{page--;lastItems='';refresh(true);};
  screen.querySelector('[data-review-next]').onclick=()=>{page++;lastItems='';refresh(true);};
  run.onclick=async()=>{run.disabled=true;try{await api('/run',{limit:Number(screen.querySelector('[data-review-limit]').value),kind:kind.value});await refresh(true);}catch(error){status.textContent=error.message;run.disabled=false;}};
  document.getElementById('data-review-open').onclick=()=>window.ArenaWorkspace.show('review-bot');
  document.addEventListener('arena:viewchange',event=>{
    clearTimeout(timer);generation++;
    if(event.detail.mode==='review-bot')refresh(true);
  });
})();
