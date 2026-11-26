/* Plays only segments of the complete, server-validated reply. No raw LLM deltas. */
(function(root){
  async function play({url,text,signal,playChunk,onChunk,fetchImpl=fetch}){
    const response=await fetchImpl(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text}),signal});
    if(!response.ok||!response.body?.getReader){const error=Error('Phát theo đoạn chưa sẵn sàng.');error.allowFallback=[404,501,503].includes(response.status)||!response.body?.getReader&&response.ok;throw error;}
    const reader=response.body.getReader(),decoder=new TextDecoder();
    let buffer='',index=0,count=null,joined='',done=false,failure=null,chain=Promise.resolve(),bytes=0;
    const expected=text.replace(/\s+/g,' ').trim();
    function event(row){
      if(signal?.aborted)throw Error('Đã hủy');
      if(done)throw Error('Dữ liệu sau kết thúc');
      if(row.type==='error')throw Error('Âm thanh bị gián đoạn.');
      if(row.type==='done'){
        if(row.count!==count||index!==count||joined!==expected)throw Error('Lời thoại chưa đầy đủ.');
        done=true;return;
      }
      if(row.type!=='audio'||row.index!==index||!Number.isInteger(row.count)||row.count<1||row.count>3||count!==null&&count!==row.count||typeof row.text!=='string'||typeof row.audio!=='string')throw Error('Thứ tự âm thanh không hợp lệ.');
      count=row.count;
      const prefix=(joined+' '+row.text).trim();
      if(!expected.startsWith(prefix)||row.index<count-1&&!/[.!?]$/.test(row.text))throw Error('Âm thanh không khớp câu trả lời đã duyệt.');
      joined=prefix;index++;
      const raw=atob(row.audio),data=Uint8Array.from(raw,c=>c.charCodeAt(0));
      if(data.length<44||String.fromCharCode(...data.slice(0,4))!=='RIFF')throw Error('Âm thanh không hợp lệ.');
      const blob=new Blob([data],{type:'audio/wav'});
      chain=chain.then(async()=>{
        if(failure||signal?.aborted)return;
        onChunk?.(row);
        const played=await playChunk(blob,row);
        if(!played)throw Error('Không phát được đoạn âm thanh.');
      }).catch(error=>{failure=error;});
    }
    try{
      while(true){
        if(signal?.aborted)throw Error('Đã hủy');
        const result=await reader.read();if(result.done)break;
        bytes+=result.value.byteLength;if(bytes>8*1024*1024)throw Error('Âm thanh vượt giới hạn.');
        buffer+=decoder.decode(result.value,{stream:true});
        let newline;
        while((newline=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,newline);buffer=buffer.slice(newline+1);if(line.trim())event(JSON.parse(line));}
        if(failure)throw failure;
      }
      buffer+=decoder.decode();if(buffer.trim())event(JSON.parse(buffer));
      if(!done)throw Error('Âm thanh kết thúc chưa đủ câu.');
      await chain;if(failure)throw failure;
      return !signal?.aborted;
    }catch(error){failure=error;await reader.cancel().catch(()=>{});await chain;throw error;}
    finally{reader.releaseLock();}
  }
  root.SpeechAudioStream={play};
  if(typeof module!=='undefined'&&module.exports)module.exports=root.SpeechAudioStream;
})(globalThis);
