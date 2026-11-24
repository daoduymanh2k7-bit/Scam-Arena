/* Local simulated inbox. No browser notification permission or external email. */
(function(root){
  'use strict';
  function remaining(message, now=Date.now()) {
    if(message.revoked_at)return 'Mã đã được thay thế';
    const seconds=Math.max(0,Math.ceil((Date.parse(message.expires_at)-now)/1000));
    return seconds ? `Còn hiệu lực ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}` : 'Mã đã hết hiệu lực';
  }
  const element=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text)e.textContent=text;return e;};
  class PhoneInbox {
    constructor(screen) {
      this.screen=screen;this.generation=0;this.messages=[];this.seen=new Set();this.readIds=new Set();this.queue=[];this.tab='all';
      this.banner=screen.querySelector('#phone-sms-banner');
      this.banner.innerHTML='<button type="button" class="phone-notice-open"><span class="phone-notice-icon"></span><span class="phone-notice-copy"><span class="phone-notice-meta"><strong></strong><time>bây giờ</time></span><span class="phone-notice-subject"></span><span class="phone-notice-preview"></span></span></button><button type="button" class="phone-notice-dismiss" aria-label="Ẩn thông báo">×</button>';
      this.banner.querySelector('.phone-notice-open').onclick=()=>{if(this.currentNotice)this.open(this.currentNotice.message_id);this.dismiss();};
      this.banner.querySelector('.phone-notice-dismiss').onclick=()=>this.dismiss();
      this.launcher=element('button','phone-inbox-launcher');this.launcher.type='button';this.launcher.setAttribute('aria-label','Mở hộp thư mô phỏng');
      this.launcher.innerHTML='<span aria-hidden="true">✉</span><span class="phone-inbox-badge"></span>';this.launcher.hidden=true;screen.append(this.launcher);
      this.overlay=element('section','phone-inbox-overlay');this.overlay.hidden=true;this.overlay.setAttribute('aria-label','Hộp thư mô phỏng');
      this.overlay.innerHTML='<button type="button" class="phone-return-call">‹ Quay lại cuộc gọi <span>● Đang diễn ra</span></button><header><button type="button" class="phone-inbox-back" hidden>‹ Hộp thư</button><h3>Hộp thư</h3><small>Chỉ có dữ liệu mô phỏng</small></header><nav class="phone-inbox-tabs" aria-label="Kênh thông báo"></nav><div class="phone-inbox-content"></div><p class="phone-inbox-status" role="status"></p>';
      screen.append(this.overlay);this.content=this.overlay.querySelector('.phone-inbox-content');this.status=this.overlay.querySelector('.phone-inbox-status');
      this.launcher.onclick=()=>this.showList();this.overlay.querySelector('.phone-return-call').onclick=()=>this.close();
      this.overlay.querySelector('.phone-inbox-back').onclick=()=>this.showList();
      for(const [value,label] of [['all','Tất cả'],['sms','Tin nhắn'],['email','Mail']]){
        const b=element('button','',label);b.type='button';b.dataset.channel=value;b.onclick=()=>{this.tab=value;this.showList();};this.overlay.querySelector('nav').append(b);
      }
      this.overlay.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();this.close();}};
    }
    setUtilities(panel, sources) {
      this.utilities=panel;this.utilitySources=sources;
      this.utilityParking=element('div');this.utilityParking.hidden=true;this.screen.append(this.utilityParking);this.utilityParking.append(panel);
      this.utilityLauncher=element('button','phone-inbox-launcher phone-tools-launcher','Tiện ích');
      this.utilityLauncher.type='button';this.utilityLauncher.hidden=true;
      this.utilityLauncher.onclick=()=>this.showTools();this.screen.append(this.utilityLauncher);
    }
    enableUtilities(enabled){if(this.utilityLauncher)this.utilityLauncher.hidden=!enabled;}
    updateUtilities(){
      if(!this.utilityView)return;
      for(const [key,source] of Object.entries(this.utilitySources))this.utilityView.querySelector(`[data-tool-${key}]`).textContent=source.textContent;
    }
    clearContent(){
      if(this.utilities && this.content.contains(this.utilities))this.utilityParking.append(this.utilities);
      this.content.replaceChildren();
    }
    showTools(){
      this.hideNotice();clearInterval(this.expiryTimer);this.openId=null;this.tab='tools';
      this.overlay.hidden=false;this.overlay.querySelector('.phone-inbox-back').hidden=true;
      this.overlay.querySelector('h3').textContent='Tiện ích cuộc gọi';this.overlay.querySelector('nav').hidden=true;
      this.utilityView=element('div','phone-call-utilities');
      this.utilityView.innerHTML='<p class="phone-context" data-tool-context></p><div class="phone-tool-actions"></div><p class="phone-evidence" data-tool-evidence></p><p role="status" data-tool-result></p>';
      this.utilityView.querySelector('.phone-tool-actions').append(this.utilities);
      this.content.replaceChildren(this.utilityView);this.status.textContent='';this.updateUtilities();
    }
    async request(path,body,signal){
      const response=await fetch(`/api/voice/inbox/${encodeURIComponent(this.session)}${path}`,body===undefined?{signal}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});
      const data=await response.json();if(!response.ok)throw Error(data.detail||'Chưa tải được thông báo.');return data;
    }
    bind(session){if(this.session===session)return this.refresh();this.reset();this.session=session;return this.refresh();}
    async refresh(){
      if(!this.session)return;
      const generation=this.generation;
      // Concurrent refreshes are coalesced; every list is a full server snapshot.
      if(this.loading)return this.loading;
      const controller=new AbortController();this.abort=controller;
      this.loading=(async()=>{
        try{
          const data=await this.request('',undefined,controller.signal);if(generation!==this.generation)return;
          this.messages=data.messages;this.canResend=!this.callEnded&&data.can_resend;
          for(const m of this.messages)if(this.readIds.has(m.message_id))m.read_at=m.read_at||new Date().toISOString();
          for(const message of [...this.messages].reverse())if(!this.seen.has(message.message_id)){
            this.seen.add(message.message_id);if(!message.read_at)this.queue.push(message);
          }
          this.updateBadge();if(!this.currentNotice)this.next();
          if(!this.overlay.hidden){if(this.openId)this.drawMessage(this.openId);else if(this.tab==='tools')this.showTools();else this.showList(false);}
        }catch(error){if(error.name!=='AbortError'&&generation===this.generation)this.status.textContent=error.message;}
        finally{if(generation===this.generation)this.loading=null;}
      })();return this.loading;
    }
    updateBadge(){
      const unread=this.messages.filter(m=>!m.read_at).length;this.launcher.hidden=!this.messages.length;
      this.launcher.querySelector('.phone-inbox-badge').textContent=unread||'';
      this.launcher.setAttribute('aria-label',`Mở hộp thư mô phỏng, ${unread} thông báo chưa đọc`);
    }
    next(){
      if(!this.overlay.hidden)return;
      let message;do{message=this.queue.shift();}while(message&&this.messages.find(m=>m.message_id===message.message_id)?.read_at);if(!message)return;
      this.currentNotice=message;this.banner.dataset.channel=message.channel;
      this.banner.querySelector('.phone-notice-icon').textContent=message.channel==='email'?'M':'✉';
      this.banner.querySelector('strong').textContent=message.sender;
      this.banner.querySelector('.phone-notice-subject').textContent=message.subject;
      this.banner.querySelector('.phone-notice-preview').textContent=message.body.split('\n')[0];
      this.banner.hidden=false;this.banner.style.animation='none';void this.banner.offsetWidth;this.banner.style.animation='';
      this.noticeTimer=setTimeout(()=>this.dismiss(),6500);
    }
    dismiss(){clearTimeout(this.noticeTimer);this.banner.hidden=true;this.currentNotice=null;this.nextTimer=setTimeout(()=>this.next(),350);}
    hideNotice(){clearTimeout(this.noticeTimer);clearTimeout(this.nextTimer);this.banner.hidden=true;this.currentNotice=null;}
    showList(focus=true){
      if(this.tab==='tools')this.tab='all';
      this.hideNotice();clearInterval(this.expiryTimer);this.openId=null;this.overlay.hidden=false;this.overlay.querySelector('.phone-inbox-back').hidden=true;
      this.overlay.querySelector('h3').textContent=this.tab==='email'?'Mail':this.tab==='sms'?'Tin nhắn':'Hộp thư';
      this.overlay.querySelector('nav').hidden=false;this.clearContent();this.status.textContent='';
      for(const b of this.overlay.querySelectorAll('nav button'))b.setAttribute('aria-pressed',String(b.dataset.channel===this.tab));
      const messages=this.messages.filter(m=>this.tab==='all'||m.channel===this.tab);
      if(!messages.length)this.content.append(element('p','phone-inbox-empty','Chưa có thông báo trong mục này.'));
      for(const message of messages){
        const b=element('button','phone-message-row'+(message.read_at?'':' is-unread'));b.type='button';
        b.append(element('span','phone-message-avatar '+message.channel,message.channel==='email'?'M':'✉'));
        const text=element('span','phone-message-summary');text.append(element('strong','',message.sender),element('span','',message.subject),element('small','',message.body.split('\n')[0]));b.append(text);b.onclick=()=>this.open(message.message_id);this.content.append(b);
      }
      if(focus)this.overlay.querySelector('.phone-return-call').focus({preventScroll:true});
    }
    async open(id){
      this.drawMessage(id);const generation=this.generation;
      try{await this.request(`/messages/${id}/read`,{});if(generation!==this.generation)return;
        this.readIds.add(id);const m=this.messages.find(x=>x.message_id===id);if(m)m.read_at=new Date().toISOString();this.updateBadge();
      }catch(error){if(generation===this.generation)this.status.textContent=error.message;}
    }
    drawMessage(id){
      this.hideNotice();clearInterval(this.expiryTimer);const message=this.messages.find(m=>m.message_id===id);if(!message)return;
      this.openId=id;this.overlay.hidden=false;this.overlay.querySelector('nav').hidden=true;this.overlay.querySelector('.phone-inbox-back').hidden=false;
      this.overlay.querySelector('h3').textContent=message.channel==='email'?'Mail':'Tin nhắn';this.clearContent();this.status.textContent='';
      const article=element('article','phone-message-reader '+message.channel);
      article.append(element('span','phone-message-channel',message.channel==='email'?'EMAIL MÔ PHỎNG':'SMS MÔ PHỎNG'),element('h4','',message.subject),element('strong','phone-message-from',message.sender));
      article.append(element('small','phone-message-date','Đến: tôi · '+new Date(message.created_at).toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'})));
      if(message.code){
        article.append(element('div','phone-message-code',message.code.slice(0,3)+' '+message.code.slice(3)));
        const ttl=element('p','phone-message-expiry');const update=()=>{ttl.textContent=remaining(message);ttl.classList.toggle('is-expired',Boolean(message.revoked_at)||Date.parse(message.expires_at)<=Date.now());};update();this.expiryTimer=setInterval(update,1000);article.append(ttl);
      }
      article.append(element('p','phone-message-text',message.body));
      if(message.code && this.canResend){
        const b=element('button','phone-message-resend','Gửi lại mã mô phỏng');b.type='button';b.onclick=async()=>{
          const generation=this.generation;b.disabled=true;try{await this.request('/resend',{});if(generation!==this.generation)return;await this.refresh();const latest=this.messages.find(m=>m.code);if(latest)await this.open(latest.message_id);}
          catch(error){if(generation===this.generation){this.status.textContent=error.message;b.disabled=false;}}
        };article.append(b);
      }
      this.content.append(article);
    }
    close(){clearInterval(this.expiryTimer);this.overlay.hidden=true;this.launcher.focus({preventScroll:true});this.next();}
    ended(){this.enableUtilities(false);this.callEnded=true;this.canResend=false;this.overlay.querySelector('.phone-return-call span').textContent='Cuộc gọi đã kết thúc';if(this.openId)this.drawMessage(this.openId);}
    reset(){
      this.generation++;this.abort?.abort();this.loading=null;clearTimeout(this.noticeTimer);clearTimeout(this.nextTimer);clearInterval(this.expiryTimer);
      this.enableUtilities(false);this.tab='all';this.utilityView=null;this.clearContent();
      this.session=null;this.callEnded=false;this.canResend=false;this.messages=[];this.seen=new Set();this.readIds=new Set();this.queue=[];this.currentNotice=null;this.openId=null;
      this.banner.hidden=true;this.overlay.hidden=true;this.launcher.hidden=true;this.overlay.querySelector('.phone-return-call span').textContent='● Đang diễn ra';
    }
  }
  root.PhoneInbox=PhoneInbox;
  if(typeof module!=='undefined'&&module.exports)module.exports={remaining};
})(globalThis);
