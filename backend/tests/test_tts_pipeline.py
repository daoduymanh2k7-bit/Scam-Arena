import io
import json
import sys
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from app.api import voice_routes as routes
from app.auth import get_current_user
from app.voice.tts_cache import AudioCache,sentence_chunks

TEXT=('Tôi gọi lại về phiếu hỗ trợ ứng dụng mà anh chị đã gửi trước đó. '
      'Phiếu ghi nhận mục lịch sử chỉ hiện màn hình trắng dù trang chủ vẫn mở được. '
      'Hiện tình trạng đó vẫn còn hay anh chị đã sử dụng được bình thường rồi?')


def test_chunks_preserve_all_words_and_negation_without_short_fragments():
    parts=sentence_chunks(TEXT)
    assert 1<len(parts)<=3 and ' '.join(parts)==TEXT
    text=TEXT+' Tôi không yêu cầu mật khẩu hoặc mã đăng nhập của anh chị.'
    assert ' '.join(sentence_chunks(text))==text
    assert sentence_chunks('Tôi không cần mã.')==['Tôi không cần mã.']
    assert sentence_chunks(TEXT+' Phiên bản 1.2 chưa cập nhật.')==[TEXT+' Phiên bản 1.2 chưa cập nhật.']


def test_cache_limits_ttl_and_never_remembers_failed_synthesis():
    now=[0];cache=AudioCache(max_bytes=8,ttl=10,clock=lambda:now[0])
    assert cache.get('a',lambda:b'12345')==(b'12345',False)
    assert cache.get('a',lambda:pytest.fail('recomputed'))==(b'12345',True)
    cache.get('b',lambda:b'67890');assert cache.size<=8 and 'a' not in cache.entries
    now[0]=11
    assert cache.get('b',lambda:b'new')==(b'new',False)
    with pytest.raises(ValueError):cache.get('bad',lambda:(_ for _ in ()).throw(ValueError()))
    assert cache.get('bad',lambda:b'ok')==(b'ok',False)


def test_cache_single_flight_shares_only_identical_keys():
    started=threading.Event();release=threading.Event();calls=[];cache=AudioCache()
    def build():started.set();release.wait(2);calls.append(1);return b'wav'
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(cache.get,'same-text-and-voice',build) for _ in range(4)]
        assert started.wait(2);release.set()
        assert all(f.result()[0]==b'wav' for f in futures)
    assert calls==[1]
    assert cache.get('different-voice',lambda:b'other')==(b'other',False)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('TTS_STREAMING_ENABLED','true')
    wav=io.BytesIO()
    with wave.open(wav,'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(bytes(100))
    synth=Mock(return_value=(wav.getvalue(),False))
    monkeypatch.setitem(sys.modules,'app.voice.synthesis',SimpleNamespace(available_caller_voices=lambda:[],synthesize_cached=synth))
    app=FastAPI();app.include_router(routes.router)
    with TestClient(app) as c:yield c,app,synth


URL='/api/voice/speak/stream/12345678-1234-1234-1234-123456789012/1'


def test_stream_requires_auth_and_rejects_stale_before_synthesis(client,monkeypatch):
    c,app,synth=client
    assert c.post(URL,json={'text':TEXT}).status_code==401
    app.dependency_overrides[get_current_user]=lambda:{'user_id':'owner'}
    def stale(*a):raise HTTPException(409,'changed')
    monkeypatch.setattr(routes,'current_audio_turn',stale)
    assert c.post(URL,json={'text':TEXT}).status_code==409
    synth.assert_not_called()


def test_stream_order_complete_text_and_midstream_change_stop(client,monkeypatch):
    c,app,synth=client;app.dependency_overrides[get_current_user]=lambda:{'user_id':'owner'}
    monkeypatch.setattr(routes,'current_audio_turn',Mock())
    res=c.post(URL,json={'text':TEXT});assert res.status_code==200
    events=[json.loads(line) for line in res.text.splitlines()]
    audios=[r for r in events if r['type']=='audio']
    assert ' '.join(r['text'] for r in audios)==TEXT
    assert [r['index'] for r in audios]==list(range(len(audios))) and events[-1]['type']=='done'
    checks=[];synth.reset_mock()
    def current(*a):
        checks.append(1)
        if len(checks)>=4:raise HTTPException(409,'regenerated')
    monkeypatch.setattr(routes,'current_audio_turn',current)
    events=[json.loads(line) for line in c.post(URL,json={'text':TEXT}).text.splitlines()]
    assert [r['type'] for r in events]==['audio','error'] and synth.call_count==1
