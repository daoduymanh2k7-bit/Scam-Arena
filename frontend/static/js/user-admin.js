(() => {
  'use strict';
  const $=id=>document.getElementById('users-'+id);
  let page=1,result=null,selected=null,sequence=0,controller=null,actionBusy=false,visible=false,poll=null;
  const date=value=>value?new Date(value).toLocaleString('vi-VN'):'Chưa ghi nhận';
  function element(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
  function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('users-error',error);}
  async function request(path='',body,signal){const r=await fetch('/api/admin/users'+path,body===undefined?{signal,cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Không xử lý được yêu cầu.');return data;}
  async function load(background=false){
    if(background&&(actionBusy||document.hidden||!visible))return;
    const seq=++sequence;controller?.abort();controller=new AbortController();if(!background)status('Đang tải danh sách…');
    const query=new URLSearchParams({search:$('search').value.trim(),state:$('state').value,role:$('role').value,page:String(page),page_size:'20'});
    try{
      const data=await request('?'+query,undefined,controller.signal);if(seq!==sequence)return;result=data;
      const pages=Math.max(1,Math.ceil(data.total/data.page_size));if(page>pages){page=pages;return load();}
      $('list').replaceChildren();$('count').textContent=`${data.total} tài khoản phù hợp`;
      if(!data.users.length)$('list').append(element('p','users-note','Không tìm thấy tài khoản phù hợp.'));
      if(data.users.length){
        const table=element('table','users-table');const caption=element('caption','users-table-caption','Danh sách tài khoản và thống kê luyện tập');table.append(caption);
        const head=element('thead'),headRow=element('tr');
        for(const [label,extra] of [['Tài khoản',false],['Trạng thái',false],['Phiên',false],['Lượt',true],['Điểm TB',true],['Đúng / đánh giá',true],['Đăng nhập gần nhất',true],['Thao tác',false]]){
          const th=element('th',extra?'users-col-extra':'',label);th.scope='col';headRow.append(th);
        }
        head.append(headRow);table.append(head);const body=element('tbody');
        for(const u of data.users){
          const row=element('tr','user-row');const account=element('th','user-account-cell');account.scope='row';
          const name=element('strong','user-account-name',u.username);name.title=u.username;
          account.append(name,element('small','user-role',(u.role==='admin'?'Quản trị viên':'Người dùng')+(u.user_id===data.current_user_id?' · Bạn':'')));
          const state=element('td');state.append(element('span','user-state'+(u.is_locked?' locked':''),u.is_locked?'Đã khóa':'Hoạt động'));
          row.append(account,state,element('td','user-number',String(u.sessions)),element('td','user-number users-col-extra',String(u.turns)),element('td','user-number users-col-extra',String(u.avg_score??'—')),element('td','user-number users-col-extra',`${u.correct}/${u.reviewed}`),element('td','user-date users-col-extra',date(u.last_login_at)));
          const action=element('td','user-action-cell');const b=element('button','users-button','Chi tiết');b.type='button';b.setAttribute('aria-label','Quản lý tài khoản '+u.username);b.onclick=()=>open(u);action.append(b);row.append(action);body.append(row);
        }
        table.append(body);$('list').append(table);
      }
      $('prev').disabled=page<=1;$('next').disabled=page>=pages;$('page').textContent=`Trang ${page} / ${pages}`;status(`Cập nhật: ${date(data.checked_at||new Date().toISOString())} · ${location.origin} · Tự cập nhật mỗi 30 giây khi mở mục này.`);
      if(selected&&!actionBusy){
        const fresh=data.users.find(u=>u.user_id===selected.user_id);
        if(fresh)void open(fresh,true);
        else{selected=null;$('detail').hidden=true;}
      }
    }catch(e){if(e.name!=='AbortError'&&seq===sequence)status(e.message,true);}
  }
  async function open(u,refresh=false){
    if(actionBusy)return;const previous=selected;selected=u;$('detail').hidden=false;$('detail-title').textContent=u.username;
    $('detail-state').textContent=u.is_locked?`Đã khóa ${date(u.locked_at)}. Lý do: ${u.lock_reason||'Chưa ghi nhận'}`:'Tài khoản đang hoạt động.';
    $('detail-meta').textContent=`Ngày tạo: ${date(u.created_at)} · Đăng nhập gần nhất: ${date(u.last_login_at)}\nLuyện tập gần nhất: ${date(u.last_practice_at)}\n${u.sessions} phiên · ${u.turns} lượt trao đổi · Điểm TB: ${u.avg_score??'—'} · Nhận định đúng: ${u.correct}/${u.reviewed}`;
    const canChange=u.is_locked||u.can_lock;
    $('action-form').hidden=!canChange;
    if(!canChange)$('detail-state').textContent+=' Không thể tự khóa tài khoản đang sử dụng hoặc khóa admin cuối cùng.';
    if(!refresh||previous?.is_locked!==u.is_locked)$('reason').value='';$('reason').required=!u.is_locked;$('reason').minLength=u.is_locked?0:3;
    $('reason-label').textContent=u.is_locked?'Lý do mở khóa (không bắt buộc)':'Lý do khóa (tối thiểu 3 ký tự)';
    $('action').textContent=u.is_locked?'Xác nhận mở khóa':'Xác nhận khóa tài khoản';$('action').disabled=false;
    if(refresh&&previous?.is_locked===u.is_locked)return;
    $('events').textContent='Đang tải lịch sử…';if(!refresh)$('detail').scrollIntoView({behavior:'auto',block:'start'});
    try{
      const events=await request('/'+encodeURIComponent(u.user_id)+'/events');if(selected?.user_id!==u.user_id)return;
      $('events').replaceChildren();if(!events.length)$('events').append(element('p','users-note','Chưa có thao tác khóa hoặc mở khóa.'));
      events.forEach(event=>{const item=element('div','users-event');item.append(element('strong','',`${event.action==='lock'?'Khóa tài khoản':'Mở khóa tài khoản'} · ${event.actor_username}`),element('small','',` · ${date(event.created_at)}`),element('p','',event.reason||'Không ghi chú thêm.'));$('events').append(item);});
    }catch(e){if(selected?.user_id===u.user_id)$('events').textContent=e.message;}
  }
  $('search-form').onsubmit=event=>{event.preventDefault();page=1;load();};
  $('refresh').onclick=()=>load();$('prev').onclick=()=>{page--;load();};$('next').onclick=()=>{page++;load();};
  $('detail-close').onclick=()=>{if(!actionBusy){selected=null;$('detail').hidden=true;}};
  $('action-form').onsubmit=async event=>{
    event.preventDefault();if(!selected||actionBusy||!$('action-form').reportValidity())return;
    const target=selected;actionBusy=true;$('action').disabled=true;
    try{
      await request('/'+encodeURIComponent(target.user_id)+'/status',{locked:!target.is_locked,expected_locked:target.is_locked,reason:$('reason').value.trim()});
      selected=null;$('detail').hidden=true;await load();status(target.is_locked?'Đã mở khóa. Người dùng cần đăng nhập lại.':'Đã khóa tài khoản và thu hồi các phiên đăng nhập.');
    }catch(e){status(e.message,true);$('action').disabled=false;}
    finally{actionBusy=false;}
  };
  document.addEventListener('arena:viewchange',event=>{
    visible=event.detail.mode==='users';clearInterval(poll);poll=null;
    if(visible){void load();poll=setInterval(()=>void load(true),30000);}
    else{sequence++;controller?.abort();}
  });
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&visible)void load(true);});
  window.addEventListener('focus',()=>{if(visible)void load(true);});
})();
