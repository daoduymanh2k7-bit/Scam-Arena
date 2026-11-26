(() => {
  const root=document.getElementById('service-status');
  if(!root)return;
  const buttons=[...root.querySelectorAll('[data-service]')],detail=document.getElementById('service-status-detail');
  const names={call:'AI cuộc gọi',message:'AI nhắn tin',stt:'Nhận diện giọng nói'};
  const states={unknown:'Chưa kiểm tra',checking:'Đang kiểm tra',ok:'Hoạt động',warning:'Cần lưu ý',unavailable:'Không khả dụng'};
  let requested=false,snapshot=null,selected=null;
  function info(key){return snapshot?.services?.[key]||{state:'unknown',message:'Đăng nhập để kiểm tra dịch vụ khi mở trang.'};}
  function render(){
    for(const button of buttons){const key=button.dataset.service,row=info(key),state=states[row.state]?row.state:'unknown';
      button.dataset.state=state;button.title=`${names[key]}: ${states[state]} — ${row.message}`;button.setAttribute('aria-label',button.title);
    }
    if(selected){const row=info(selected);detail.querySelector('strong').textContent=`${names[selected]} · ${states[row.state]||states.unknown}`;
      detail.querySelector('p').textContent=row.message;
      detail.querySelector('small').textContent=[row.model?`Model: ${row.model}`:'',Number.isFinite(row.latency_ms)?`Thời gian thử: ${(row.latency_ms/1000).toFixed(1)} giây`:'',snapshot?.checked_at?`Kiểm tra: ${new Date(snapshot.checked_at).toLocaleString('vi-VN')}`:'','Giữ kết quả đến khi tải lại trang.'].filter(Boolean).join('\n');
    }
  }
  function close(){selected=null;detail.hidden=true;buttons.forEach(b=>b.setAttribute('aria-expanded','false'));}
  buttons.forEach(button=>button.addEventListener('click',()=>{
    const key=button.dataset.service;if(selected===key){close();return;}
    selected=key;detail.hidden=false;buttons.forEach(b=>b.setAttribute('aria-expanded',String(b===button)));render();
  }));
  document.addEventListener('click',event=>{if(!root.contains(event.target))close();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
  async function checkOnce(){
    if(requested||document.body.dataset.authenticated!=='true')return;
    requested=true;snapshot={services:Object.fromEntries(buttons.map(b=>[b.dataset.service,{state:'checking',message:'Đang gửi yêu cầu thử nhỏ đến dịch vụ.'}]))};render();
    try{const response=await fetch('/api/service-status',{method:'POST',credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error();snapshot=await response.json();}
    catch(_){snapshot={services:Object.fromEntries(buttons.map(b=>[b.dataset.service,{state:'unknown',message:'Chưa kiểm tra được. Hãy tải lại trang để thử lại.'}]))};}
    render();
  }
  document.addEventListener('arena:authenticated',checkOnce);render();void checkOnce();
})();
