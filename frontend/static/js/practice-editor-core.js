(function(root){
  'use strict';
  const intents={verify:'Tự xác minh',refuse:'Từ chối',doubt:'Nghi ngờ / hỏi thêm',comply:'Đồng ý',share_sensitive:'Đã chia sẻ mã / thông tin',transfer_money:'Đã chuyển tiền',hang_up:'Muốn kết thúc',unknown:'Chưa rõ ý'};
  const terminals={END_SAFE:'Kết thúc an toàn',END_UNSAFE:'Kết thúc rủi ro',END_NEUTRAL:'Kết thúc chưa đủ thông tin'};
  const clone=value=>JSON.parse(JSON.stringify(value));
  function stage(id='intro') {
    return {id,objective:'Trao đổi rõ nội dung và phản hồi đúng tình huống.',tactics:[],requested_action:'other',opening_line:'',fallback_lines:[],max_turns:3,default_next_stage_id:id,timeout_next_stage_id:'END_NEUTRAL',transitions:Object.keys(intents).map(on_intent=>({on_intent,next_stage_id:on_intent==='hang_up'?'END_NEUTRAL':id}))};
  }
  function fresh() {
    const now=new Date().toISOString();const first=stage();first.transitions.find(t=>t.on_intent==='comply').next_stage_id='END_SAFE';
    return {schema_version:1,id:'practice-custom-'+crypto.randomUUID().slice(0,8),version:1,status:'published',title:'Kịch bản mới',category:'other',family:'delivery',scenario_kind:'benign',difficulty:'beginner',locale:'vi-VN',summary:'Cuộc gọi mô phỏng để luyện phản xạ và xác minh thông tin.',user_context:'',persona:{name:'Người liên hệ dịch vụ',claimed_role:'Nhân viên giao nhận',speaking_style:'Lịch sự, ngắn gọn, giải thích khi được hỏi.',pressure_level:1},start_stage_id:'intro',stages:[first],red_flags:[],scoring:{base_score:60,rules:Object.keys(intents).map(intent=>({intent,points_delta:0,feedback:'Xem hành động và bằng chứng trong tình huống.',critical:false}))},case_blueprint:{evidence:'',official:''},lesson_summary:'',created_at:now,updated_at:now,published_at:now};
  }
  function duplicate(doc){const copy=clone(doc);copy.id='practice-custom-'+crypto.randomUUID().slice(0,8);copy.title=copy.title.slice(0,100)+' — bản sao';copy.version=1;copy.created_at=new Date().toISOString();return copy;}
  function references(doc,id){return doc.stages.filter(s=>s.id!==id&&(s.default_next_stage_id===id||s.timeout_next_stage_id===id||s.transitions.some(t=>t.next_stage_id===id))).map(s=>s.id).concat(doc.red_flags.filter(f=>f.stage_id===id).map(f=>'dấu hiệu '+f.id),doc.scoring.rules.filter(r=>r.stage_id===id).map(()=> 'luật điểm'));}
  function preview(doc,current,intent,visits={},count=0,unknown=0){
    const s=doc.stages.find(s=>s.id===current);if(!s)throw Error('Không tìm thấy bước để chạy thử.');
    const nextVisits={...visits,[current]:(visits[current]||0)+1};
    const edge=s.transitions.find(t=>t.on_intent===intent);let target=edge?.next_stage_id;
    let nextUnknown=edge?0:unknown+1;
    if(!target){
      if(nextVisits[current]>=s.max_turns){target=s.timeout_next_stage_id;nextUnknown=0;}
      else if(nextUnknown>=2)target='END_NEUTRAL';
      else target=current;
    }
    if(count+1>=12&&!terminals[target])target='END_NEUTRAL';
    return {current:target,visits:nextVisits,count:count+1,unknown:nextUnknown,ended:Boolean(terminals[target])};
  }
  const api={intents,terminals,clone,stage,fresh,duplicate,references,preview};root.PracticeEditor=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
