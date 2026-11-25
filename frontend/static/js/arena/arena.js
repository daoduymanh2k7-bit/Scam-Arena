(() => {
  const $=id=>document.getElementById(id);
  const workspace=$('message-mode'),session=$('arena-session'),result=$('arena-result'),empty=$('message-empty');
  const transcriptBox=$('arena-transcript'),textInput=$('arena-text-input'),micButton=$('arena-mic-btn');
  const sendButton=$('arena-send-btn'),status=$('arena-status'),audioPlayer=$('arena-audio-player');
  const drafts=new Map();
  let scenario=null,sessionId=null,busy=false,callEnded=false,lastScammerAt=null,revision=0;
  let mediaRecorder=null,recording=false,chunks=[],voiceEnabled=false,cancelSpeech=null,speechController=null;
  let opening=null;
  function setStatus(text){status.textContent=text||'';}
  function setBusy(value){
    busy=value;const disabled=value||callEnded||!sessionId;
    sendButton.disabled=disabled||recording||!textInput.value.trim();textInput.disabled=disabled;micButton.disabled=disabled;
    $('arena-finish-btn').disabled=value||!sessionId;
    $('arena-typing').hidden=!value;transcriptBox.setAttribute('aria-busy',String(value));
  }
  function resizeInput(){textInput.style.height='auto';textInput.style.height=Math.min(textInput.scrollHeight,112)+'px';}
  function stopAudio(){speechController?.abort();speechController=null;cancelSpeech?.();cancelSpeech=null;audioPlayer.pause();audioPlayer.removeAttribute('src');audioPlayer.load();}
  function stopRecording(){
    recording=false;
    if(mediaRecorder){mediaRecorder.ondataavailable=null;if(mediaRecorder.state!=='inactive')mediaRecorder.stop();mediaRecorder.stream.getTracks().forEach(t=>t.stop());}
    mediaRecorder=null;chunks=[];micButton.textContent='🎙';micButton.setAttribute('aria-label','Ghi âm tin nhắn');
  }
  function openingState(){
    if(sessionId)drafts.set(sessionId,textInput.value);
    revision++;stopAudio();stopRecording();sessionId=null;scenario=null;callEnded=false;
    session.hidden=false;result.hidden=true;empty.hidden=true;workspace.classList.add('has-conversation');
    transcriptBox.replaceChildren();textInput.value='';textInput.placeholder='Aa';resizeInput();
    $('arena-scenario-label').textContent='Cuộc trò chuyện mô phỏng';$('arena-finish-btn').textContent='Kết thúc';$('arena-finish-btn').hidden=false;
    $('message-open-error').hidden=true;setBusy(true);return revision;
  }
  async function speak(text,token){
    if(!voiceEnabled){lastScammerAt=Date.now();return;}
    stopAudio();const controller=new AbortController();speechController=controller;
    try{
      const blob=await Api.speakText(text,null,null,controller.signal);if(token!==revision||!voiceEnabled)return;
      const url=URL.createObjectURL(blob);audioPlayer.src=url;
      await new Promise(resolve=>{
        const done=()=>{audioPlayer.removeEventListener('ended',done);audioPlayer.removeEventListener('error',done);URL.revokeObjectURL(url);if(cancelSpeech===done)cancelSpeech=null;resolve();};
        cancelSpeech=done;audioPlayer.addEventListener('ended',done,{once:true});audioPlayer.addEventListener('error',done,{once:true});audioPlayer.play().catch(done);
      });
    }catch(error){if(token===revision&&error.name!=='AbortError')setStatus('Chưa phát được giọng đọc. Bạn vẫn có thể đọc tin nhắn.');}
    finally{if(speechController===controller)speechController=null;}
    if(token===revision)lastScammerAt=Date.now();
  }
  const intentNames = {
    verify: "Muốn tự xác minh", refuse: "Từ chối", hang_up: "Muốn kết thúc cuộc gọi",
    doubt: "Nghi ngờ", comply: "Đồng ý làm theo", share_sensitive: "Chia sẻ thông tin nhạy cảm",
    transfer_money: "Đồng ý chuyển tiền", unknown: "Chưa nhận diện rõ",
  };
  const intentMethods = { saved: "lịch sử đã lưu", rule: "luật an toàn", rasa: "bộ nhận diện Rasa", llm: "LLM", fallback: "dự phòng" };
  const lineSources = {
    cache_exact: "LLM (dùng lại câu khớp chính xác từ bộ nhớ)",
    cache_pool: "LLM (dùng lại câu trong bộ nhớ)", llm: "LLM (vừa tạo câu này)", fixed: "luật/kịch bản cố định",
  };
  function addBubble(text, role, metadata = null) {
    const owner=sessionId, token=revision;
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role === "user" ? "user" : "scammer"}`;
    const content = document.createElement("div");
    content.className = "bubble-text";
    content.textContent = text;
    bubble.appendChild(content);
    const footer = document.createElement("div");
    footer.className = "message-bubble-footer";
    const time = document.createElement("time");
    const timestamp=metadata?.created_at?new Date(metadata.created_at):new Date();
    time.dateTime = timestamp.toISOString();
    time.textContent = timestamp.toLocaleTimeString("vi-VN", {hour:"2-digit",minute:"2-digit"});
    footer.append(time);
    if (metadata?.intent || metadata?.line_source) {
      const info = document.createElement("details");
      info.className = "message-bubble-info";
      const toggle = document.createElement("summary");
      toggle.textContent = "i";
      toggle.setAttribute("aria-label", "Xem nguồn và thông tin nhận diện tin nhắn");
      const detail = document.createElement("div");
      if (metadata.intent) detail.textContent = `Nhận diện: ${intentNames[metadata.intent] || metadata.intent} · ${intentMethods[metadata.intent_method] || metadata.intent_method}`;
      else detail.textContent = `Nguồn: ${lineSources[metadata.line_source] || metadata.line_source} · ${metadata.line_latency_ms ?? 0} ms`;
      info.append(toggle, detail);
      footer.append(info);
    }
    bubble.append(footer);
    if (role !== "user" && metadata?.turn_no != null) {
      const options = document.createElement("details");
      options.className = "bubble-options";
      const summary = document.createElement("summary");
      summary.textContent = "Tùy chọn trả lời";
      const actions = document.createElement("div");
      actions.className = "bubble-actions";
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "bubble-action";
      retry.textContent = "Trả lời lại câu này";
      retry.addEventListener("click", async () => {
        if(busy||recording||callEnded||token!==revision)return;
        setBusy(true);retry.disabled = true;
        retry.textContent = "Đang tạo câu mới…";
        try {
          const alternative = await Api.regenerateLine(owner, metadata.turn_no, metadata.line_id);
          if(token!==revision||owner!==sessionId)return;
          addBubble(alternative.bot_text, "scammer", { line_source: alternative.line_source,
            line_latency_ms: alternative.line_latency_ms, line_id: alternative.line_id, turn_no: alternative.turn_no });
          setStatus("Đã thêm câu trả lời mới; câu cũ vẫn được giữ lại.");
          await speak(alternative.bot_text,token);
          if(token!==revision)return;
          setStatus("Đến lượt bạn. Hãy bình tĩnh trả lời hoặc yêu cầu xác minh.");
        } catch (error) {
          if(token!==revision)return;
          setStatus(`Chưa tạo được câu trả lời mới: ${error.message}`);
          retry.disabled = false;
          retry.textContent = "Trả lời lại câu này";
        } finally {if(token===revision)setBusy(false);}
      });
      actions.appendChild(retry);
      if (metadata.line_id != null) {
        const like = document.createElement("button");
        like.type = "button";
        like.className = "bubble-action";
        like.textContent = "♡ Thích câu này";
        like.addEventListener("click", async () => {
          like.disabled = true;
          try {
            await Api.likeLine(owner, metadata.turn_no, metadata.line_id);
            if(token!==revision)return;
            like.textContent = "♥ Đã thích";
          } catch (error) {
            if(token!==revision)return;
            like.disabled = false;
            setStatus(`Chưa ghi nhận được lượt thích: ${error.message}`);
          }
        });
        actions.appendChild(like);
      }
      options.append(summary, actions);
      bubble.appendChild(options);
    }
    transcriptBox.appendChild(bubble);
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  }

  async function showScammer(response,token){
    if(token!==revision)return;
    $('arena-typing').hidden=true;
    if(response.bot_text)addBubble(response.bot_text,'scammer',{line_source:response.line_source||'fixed',line_latency_ms:response.line_latency_ms??0,line_id:response.line_id,turn_no:response.ended?null:response.turn_no});
    callEnded=Boolean(response.ended);
    await speak(response.bot_text||'',token);if(token!==revision)return;
    $('arena-finish-btn').textContent=callEnded?'Xem kết quả':'Kết thúc';
    setStatus(callEnded?'Cuộc trò chuyện đã kết thúc. Bạn có thể xem kết quả.':response.intent==='unknown'?'Bạn có thể diễn đạt rõ hơn để tiếp tục.':'');
  }
  async function newConversation(){
    if(opening===revision)return;
    const token=openingState();opening=token;setStatus('Đang mở tin nhắn mới…');
    try{
      const next=await Api.randomScenario();if(token!==revision)return;scenario=next;
      const response=await Api.startCall(next.key,'message');if(token!==revision)return;
      sessionId=response.session_id;await showScammer(response,token);
    }catch(error){
      if(token!==revision)return;scenario=null;sessionId=null;session.hidden=true;empty.hidden=false;
      $('message-open-error').textContent='Chưa mở được cuộc trò chuyện: '+error.message;$('message-open-error').hidden=false;
    }finally{if(opening===token)opening=null;if(token===revision)setBusy(false);}
  }
  async function openConversation(row){
    const token=openingState();sessionId=row.session_id;setStatus('Đang tải tin nhắn…');
    try{
      const data=await Api.callTranscript(row.session_id);if(token!==revision)return;
      if(data.interaction_mode&&data.interaction_mode!=='message')throw Error('Đây không phải hội thoại nhắn tin.');
      scenario={key:'saved'};callEnded=Boolean(data.ended||data.abandoned||row.ended_at||row.abandoned);
      for(const message of data.messages)addBubble(message.text,message.role==='player'?'user':'scammer',{intent:message.intent,intent_method:"saved",created_at:message.created_at});
      textInput.value=drafts.get(sessionId)||'';resizeInput();lastScammerAt=Date.now();
      $('arena-finish-btn').textContent=callEnded?'Xem kết quả':'Kết thúc';$('arena-finish-btn').hidden=Boolean(data.abandoned||row.abandoned);
      textInput.placeholder=callEnded?'Cuộc trò chuyện đã kết thúc':'Aa';
      setStatus(data.abandoned||row.abandoned?'Hội thoại này đã bỏ dở. Hãy tạo tin nhắn mới.':callEnded?'Hội thoại đã kết thúc. Bạn vẫn có thể đọc lại.':'');
    }catch(error){if(token===revision){scenario=null;callEnded=true;setStatus('Không tải được tin nhắn: '+error.message);}}
    finally{if(token===revision)setBusy(false);}
  }
  async function sendReply(text,elapsed){
    const answer=text.trim();if(!answer||busy||callEnded||!scenario||!sessionId||recording)return;
    const owner=sessionId,token=revision;setBusy(true);setStatus('Đang gửi…');
    try{
      const response=await Api.submitCallTurn(owner,answer,elapsed);
      if(drafts.get(owner)?.trim()===answer)drafts.delete(owner);
      if(token!==revision)return;
      addBubble(answer,'user',{intent:response.intent,intent_method:response.intent_method});
      if(textInput.value.trim()===answer){textInput.value='';drafts.delete(owner);resizeInput();}
      await showScammer(response,token);
    }catch(error){if(token===revision)setStatus('Chưa gửi được tin nhắn: '+error.message);}
    finally{if(token===revision){setBusy(false);if(!callEnded)textInput.focus({preventScroll:true});}}
  }
  async function toggleRecording(){
    if(busy||callEnded||!sessionId)return;
    const token=revision;
    if(recording){
      recording=false;const recorder=mediaRecorder;micButton.textContent='…';setBusy(true);
      const stopped=new Promise(resolve=>recorder.addEventListener('stop',resolve,{once:true}));recorder.stop();await stopped;
      recorder.stream.getTracks().forEach(track=>track.stop());if(token!==revision)return;const blob=new Blob(chunks,{type:recorder.mimeType||'audio/webm'});
      try{const data=await Api.transcribeAudio(blob);if(token!==revision)return;if(!data.text?.trim())throw Error('Không nhận diện được lời nói.');setBusy(false);await sendReply(data.text,lastScammerAt?(Date.now()-lastScammerAt)/1000:null);}
      catch(error){if(token===revision)setStatus('Chưa nhận diện được: '+error.message);}
      finally{if(token===revision){micButton.textContent='🎙';setBusy(false);}}
      return;
    }
    try{
      setBusy(true);$('arena-typing').hidden=true;
      const stream=await navigator.mediaDevices.getUserMedia({audio:true});if(token!==revision){stream.getTracks().forEach(track=>track.stop());return;}
      chunks=[];mediaRecorder=new MediaRecorder(stream);mediaRecorder.ondataavailable=event=>{if(token===revision&&event.data.size)chunks.push(event.data);};
      mediaRecorder.start();recording=true;micButton.textContent='⏹';micButton.setAttribute('aria-label','Dừng ghi âm');sendButton.disabled=true;setStatus('Đang ghi âm. Bấm dừng để gửi.');
    }catch(error){if(token===revision)setStatus('Không truy cập được micro: '+error.message);}
    finally{if(token===revision)setBusy(false);}
  }
  async function finishSession(){
    if(!sessionId||busy)return;if(recording){setStatus('Dừng ghi âm trước khi kết thúc.');return;}
    const owner=sessionId,token=revision;stopAudio();setBusy(true);session.hidden=true;result.hidden=false;
    $('arena-score').textContent='…';$('arena-badge').textContent='Đang xem kết quả';
    try{
      await Api.finishCall(owner);if(token!==revision)return;callEnded=true;
      const score = await Api.callSummary(owner);
      if(token!==revision)return;
      $("arena-score").textContent = String(score.total_score);
      $("arena-badge").textContent = score.badge || "Kết quả luyện tập";
      $("arena-latency").textContent = score.avg_response_latency == null
        ? "Chưa có dữ liệu thời gian phản hồi."
        : `Thời gian phản hồi trung bình: ${score.avg_response_latency.toFixed(1)} giây (chỉ là chỉ số tham khảo).`;
      const list = $("arena-mistakes");
      list.replaceChildren();
      (score.mistakes || []).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = `${item.severity === "HIGH" ? "🔴" : "🟡"} ${item.mistake}`;
        list.appendChild(li);
      });
      $("arena-mistakes-wrap").hidden = !score.mistakes?.length;
      $("arena-no-mistakes").hidden = !!score.mistakes?.length;
      const feedbackList = $("arena-feedback");
      feedbackList.replaceChildren();
      (score.feedback || []).forEach((item) => {
        const li = document.createElement("li");
        const change = item.score_delta > 0 ? `+${item.score_delta}` : String(item.score_delta);
        const tactic = item.tactic ? ` · Chiêu: ${item.tactic}` : "";
        li.textContent = `Lượt ${item.turn_no} · ${item.intent} · ${change}${tactic}: ${item.feedback}`;
        feedbackList.appendChild(li);
      });
      $("arena-feedback-wrap").hidden = !score.feedback?.length;
      $("arena-lesson").textContent = score.lesson_summary || "";
      $("arena-lesson").hidden = !score.lesson_summary;
      const redFlags = $("arena-redflags");
      redFlags.replaceChildren();
      (score.red_flags || []).forEach((flag) => {
        const li = document.createElement("li");
        li.textContent = `${flag.title} (${flag.severity}): ${flag.explanation}`;
        redFlags.appendChild(li);
      });
      $("arena-redflags-wrap").hidden = !score.red_flags?.length;
      if (window.ArenaHistory) setTimeout(() => window.ArenaHistory.refreshAll(), 1200);
    } catch (error) {
      if(token!==revision)return;
      $("arena-badge").textContent = `Chưa chấm được: ${error.message}`;
      $("arena-score").textContent = "—";
    } finally {if(token===revision)setBusy(false);}
  }

  textInput.addEventListener('input',()=>{resizeInput();if(sessionId)drafts.set(sessionId,textInput.value);sendButton.disabled=busy||recording||callEnded||!textInput.value.trim();});
  textInput.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();sendButton.click();}});
  sendButton.onclick=()=>sendReply(textInput.value,lastScammerAt?(Date.now()-lastScammerAt)/1000:null);
  micButton.onclick=toggleRecording;
  $('message-new').onclick=newConversation;$('message-empty-new').onclick=newConversation;$('arena-restart-btn').onclick=newConversation;
  $('message-result-back').onclick=()=>{result.hidden=true;session.hidden=false;setBusy(false);};
  $('arena-finish-btn').onclick=finishSession;
  $('message-voice').onclick=()=>{voiceEnabled=!voiceEnabled;$('message-voice').setAttribute('aria-pressed',String(voiceEnabled));$('message-voice').setAttribute('aria-label',voiceEnabled?'Tắt giọng đọc':'Bật giọng đọc');if(!voiceEnabled)stopAudio();};
  document.addEventListener('arena:authenticated',()=>{revision++;sessionId=null;drafts.clear();callEnded=true;session.hidden=true;result.hidden=true;empty.hidden=false;workspace.classList.remove('has-conversation');stopRecording();stopAudio();setBusy(false);});
  document.addEventListener('arena:viewchange',event=>{
    if(event.detail.previous==='message'&&event.detail.mode!=='message'){
      if(sessionId)drafts.set(sessionId,textInput.value);revision++;stopRecording();stopAudio();opening=null;
    }
    if(event.detail.mode==='message'&&document.body.dataset.authenticated==='true'){
      if(sessionId)void openConversation({session_id:sessionId});
    }
  });
  setBusy(false);
})();
