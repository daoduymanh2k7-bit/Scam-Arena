(() => {
  const dialog=document.getElementById('quick-tutorial');if(!dialog)return;
  const slides=[
    {icon:'01',title:'Bắt đầu một tình huống',description:'Chọn Cuộc gọi hoặc Nhắn tin ở thanh bên, rồi bấm Bắt đầu. Bạn sẽ trò chuyện với một nhân vật trong tình huống mô phỏng.'},
    {icon:'02',title:'Bạn đang ở trong hoàn cảnh nào?',description:'Mỗi cuộc gọi có một bối cảnh giả định: những việc được xem là đã xảy ra trước đó. Hãy đọc khung “Bối cảnh giả định của bạn” trên phụ đề trước khi trả lời.',example:'Ví dụ: tài khoản của bạn không đăng nhập được. Bạn hoặc người thân đã liên hệ bộ phận hỗ trợ. Giờ có người gọi lại về yêu cầu đó — bạn sẽ nhập vai người đang chờ được hỗ trợ.'},
    {icon:'03',title:'Phản hồi và tự kiểm tra',description:'Nói khi điện thoại hiện “Đang nghe bạn”. Xem mục “Máy nghe bạn nói” để biết bản chép có đúng không. Bạn có thể mở hồ sơ và tin nhắn mô phỏng trong điện thoại để đối chiếu.',example:'Có yêu cầu hỗ trợ từ trước chưa có nghĩa người gọi chắc chắn đáng tin. Chỉ dùng dữ liệu mô phỏng, không cung cấp thông tin cá nhân thật.'}
  ];
  let index=0,shown=false,lastFocus=null;
  const el=id=>document.getElementById(id);
  function render(){const s=slides[index];el('quick-tutorial-icon').textContent=s.icon;el('quick-tutorial-step').textContent=`${index+1} / ${slides.length}`;
    el('quick-tutorial-title').textContent=s.title;el('quick-tutorial-description').textContent=s.description;
    el('quick-tutorial-example').textContent=s.example||'';el('quick-tutorial-example').hidden=!s.example;
    el('quick-tutorial-prev').hidden=index===0;el('quick-tutorial-next').textContent=index===slides.length-1?'Đã hiểu, bắt đầu thôi':'Tiếp tục →';
    [...el('quick-tutorial-dots').children].forEach((dot,i)=>dot.classList.toggle('is-current',i===index));
  }
  function open(){index=0;shown=true;lastFocus=document.activeElement;render();if(!dialog.open)dialog.showModal();el('quick-tutorial-next').focus();}
  function finish(){dialog.close();if(lastFocus?.isConnected)lastFocus.focus({preventScroll:true});
    void fetch('/api/auth/onboarding/complete',{method:'POST',credentials:'same-origin',keepalive:true}).catch(()=>{});
  }
  el('quick-tutorial-next').onclick=()=>{if(index===slides.length-1)finish();else{index++;render();}};
  el('quick-tutorial-prev').onclick=()=>{if(index>0){index--;render();}};
  el('quick-tutorial-skip').onclick=finish;
  dialog.addEventListener('cancel',event=>{event.preventDefault();finish();});
  el('quick-tutorial-replay').onclick=open;
  function firstVisit(user){
    if(shown||user?.onboarding_completed!==false)return;
    shown=true;
    // Wait until normal workspace selection finishes; it closes open dialogs.
    queueMicrotask(open);
  }
  document.addEventListener('arena:authenticated',event=>firstVisit(event.detail?.user));
  firstVisit(window.ArenaCurrentUser);
})();
