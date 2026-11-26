"""On-demand connectivity probes, coalesced across simultaneous page loads."""
import asyncio
import io
import os
import time
import wave
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,Response
from app.auth import get_current_user
from app.arena import line_generator as lines
from app.arena.xapikey_client import settings

router=APIRouter(prefix='/api/service-status',tags=['service status'])
_task=None
_cached=None
_until=0.


def probe_llm(mode):
    start=time.monotonic()
    available=any(os.getenv(k,'').strip() for k in ['GEMINI_API_KEY','GROQ_API_KEY','OPENROUTER_API_KEY']) or bool(settings(mode)[0])
    if not available:return {'state':'unavailable','message':'Chưa cấu hình dịch vụ AI.'}
    if os.getenv('LINE_LLM_ENABLED','false').lower() not in {'true','1'}:
        return {'state':'unknown','message':'AI đang tắt trong cấu hình.'}
    context={'interaction_mode':mode,'scenario_kind':'benign','sample_line':'Xin chào, tôi có thể hỗ trợ bạn không?',
             'player_text':'Xin chào','requested_action':'other','recent_turns':[]}
    try:
        model=os.getenv('GEMINI_MODEL','gemini-2.5-flash')
        text=lines._request_line(context,model,3)
        if not lines.validate_line(text,context['player_text'],context):raise ValueError('invalid_response')
        used=context.get('_generated_model',model)
        ms=round((time.monotonic()-start)*1000)
        primary=next((os.getenv(variable,default) for key,variable,default in [
            ('GEMINI_API_KEY','GEMINI_MODEL','gemini-2.5-flash'),('GROQ_API_KEY','GROQ_MODEL','openai/gpt-oss-20b'),
            ('OPENROUTER_API_KEY','OPENROUTER_MODEL','openrouter/free')] if os.getenv(key,'').strip()),settings(mode)[1])
        fallback=used!=primary
        return {'state':'warning' if fallback or ms>8000 else 'ok','model':used,'latency_ms':ms,
                'message':'Đang dùng dịch vụ/model dự phòng.' if fallback else 'Tạo câu trả lời thử thành công.'}
    except Exception:
        return {'state':'unavailable','message':'Chưa tạo được phản hồi thử. Dịch vụ có thể lỗi hoặc quá thời gian chờ.'}


def probe_stt():
    if os.getenv('STT_PROVIDER','deepgram')!='deepgram':
        return {'state':'unknown','message':'Đang dùng STT cục bộ; chưa chạy thử nhận diện.'}
    if not os.getenv('DEEPGRAM_API_KEY','').strip():
        return {'state':'unavailable','message':'Chưa cấu hình dịch vụ STT.'}
    from app.voice.deepgram import transcribe,metadata
    from app.voice.scheduling import SpeechBusy
    audio=io.BytesIO()
    with wave.open(audio,'wb') as w:
        w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(bytes(8000))
    start=time.monotonic()
    try:
        transcribe(audio.getvalue(),user_id='service-status-probe')
        return {'state':'ok','model':metadata()['model'],'latency_ms':round((time.monotonic()-start)*1000),
                'message':'API STT nhận âm thanh thử thành công. Không đánh giá độ chính xác nghe.'}
    except SpeechBusy:
        return {'state':'warning','message':'STT đang bận hoặc bị giới hạn yêu cầu.'}
    except Exception:
        return {'state':'unavailable','message':'API STT chưa xử lý được âm thanh thử.'}


async def collect():
    async def bounded(fn,*args):
        try:return await asyncio.wait_for(asyncio.to_thread(fn,*args),timeout=35)
        except Exception:return {'state':'unavailable','message':'Kiểm tra quá thời gian chờ.'}
    call,message,stt=await asyncio.gather(bounded(probe_llm,'call'),bounded(probe_llm,'message'),bounded(probe_stt))
    return {'checked_at':datetime.now(timezone.utc).isoformat(),'services':{'call':call,'message':message,'stt':stt}}


@router.post('')
async def snapshot(response:Response,user=Depends(get_current_user)):
    global _task,_cached,_until
    response.headers['Cache-Control']='no-store'
    # No background polling. Brief reuse prevents reload storms creating paid requests.
    if _cached is not None and time.monotonic()<_until:return _cached
    if _task is None or _task.done():_task=asyncio.create_task(collect())
    task=_task
    result=await asyncio.shield(task)
    _cached=result;_until=time.monotonic()+30
    return result
