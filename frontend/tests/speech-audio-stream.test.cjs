const {test}=require('node:test');
const assert=require('node:assert/strict');
const {play}=require('../static/js/speech-audio-stream.js');
const audio=Buffer.concat([Buffer.from('RIFF'),Buffer.alloc(44)]).toString('base64');
function response(events){return new Response(events.map(x=>JSON.stringify(x)+'\n').join(''));}
const first='Tôi không cần mã đăng nhập của anh chị.';
const second='Anh chị có thể tự kiểm tra qua kênh chính thức.';
const events=[{type:'audio',index:0,count:2,text:first,audio},{type:'audio',index:1,count:2,text:second,audio},{type:'done',count:2}];
test('segments play in sequence, preserving the approved sentence including negation',async()=>{
 const heard=[];let active=0;
 assert.equal(await play({url:'/',text:first+' '+second,fetchImpl:async()=>response(events),playChunk:async(b,r)=>{assert.equal(active++,0);heard.push(r.text);await Promise.resolve();active--;return true;}}),true);
 assert.deepEqual(heard,[first,second]);
});
test('wrong content and unordered packets are never played',async()=>{
 for(const change of [{...events[0],text:'Tôi cần mã đăng nhập.'},{...events[0],index:1}]){
  let plays=0;
  await assert.rejects(play({url:'/',text:first+' '+second,fetchImpl:async()=>response([change]),playChunk:async()=>{plays++;return true;}}));
  assert.equal(plays,0);
 }
});
test('stale turn never permits classic fallback; disabled feature does',async()=>{
 await assert.rejects(play({url:'/',text:first,fetchImpl:async()=>new Response('',{status:409}),playChunk:async()=>true}),e=>!e.allowFallback);
 await assert.rejects(play({url:'/',text:first,fetchImpl:async()=>new Response('',{status:404}),playChunk:async()=>true}),e=>e.allowFallback);
});
test('cancellation prevents queued audio from entering another call',async()=>{
 const controller=new AbortController();const heard=[];
 const result=await play({url:'/',text:first+' '+second,signal:controller.signal,fetchImpl:async()=>response(events),playChunk:async(b,r)=>{heard.push(r.index);controller.abort();return true;}}).catch(()=>false);
 assert.equal(result,false);assert.deepEqual(heard,[0]);
});
test('incomplete stream is reported without requesting or replaying the full response',async()=>{
 let requests=0;
 await assert.rejects(play({url:'/',text:first+' '+second,fetchImpl:async()=>{requests++;return response([events[0]]);},playChunk:async()=>true}));
 assert.equal(requests,1);
});
