from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import Mock
import pytest
from app.api import service_status_routes as routes
from app.auth import get_current_user


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(routes,'_task',None);monkeypatch.setattr(routes,'_cached',None);monkeypatch.setattr(routes,'_until',0)


def test_requires_login_and_reuses_short_snapshot(monkeypatch):
    calls=[]
    async def fake():
        calls.append(1)
        return {'checked_at':'2026-11-26T00:00:00+00:00','services':{}}
    monkeypatch.setattr(routes,'collect',fake)
    app=FastAPI();app.include_router(routes.router)
    with TestClient(app) as client:
        assert client.post('/api/service-status').status_code==401
        app.dependency_overrides[get_current_user]=lambda:{'user_id':'test'}
        assert client.post('/api/service-status').status_code==200
        assert client.post('/api/service-status').headers['cache-control']=='no-store'
        assert len(calls)==1
        monkeypatch.setattr(routes,'_until',0)
        assert client.post('/api/service-status').status_code==200
        assert len(calls)==2


def test_llm_probes_use_mode_and_do_not_expose_errors(monkeypatch):
    monkeypatch.setenv('LINE_LLM_ENABLED','true')
    for key in ['GEMINI_API_KEY','GROQ_API_KEY','OPENROUTER_API_KEY']:monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv('XAPIKEY_CALL_API_KEY','secret-call');monkeypatch.setenv('XAPIKEY_MESSAGE_API_KEY','secret-message')
    seen=[]
    def generate(ctx,model,timeout):
        seen.append(ctx['interaction_mode']);ctx['_generated_model']=routes.settings(ctx['interaction_mode'])[1]
        return 'Xin chào, tôi có thể giúp gì?'
    monkeypatch.setattr(routes.lines,'_request_line',generate)
    assert routes.probe_llm('call')['state']=='ok'
    assert routes.probe_llm('message')['state']=='ok'
    assert seen==['call','message']
    monkeypatch.setattr(routes.lines,'_request_line',Mock(side_effect=RuntimeError('SECRET key detail')))
    value=routes.probe_llm('call')
    assert value['state']=='unavailable' and 'SECRET' not in str(value)


def test_stt_uses_synthetic_audio_and_no_user_microphone(monkeypatch):
    from app.voice import deepgram
    monkeypatch.setenv('STT_PROVIDER','deepgram');monkeypatch.setenv('DEEPGRAM_API_KEY','test')
    request=Mock(return_value='');monkeypatch.setattr(deepgram,'transcribe',request)
    assert routes.probe_stt()['state']=='ok'
    assert request.call_args.args[0].startswith(b'RIFF')
    assert request.call_args.kwargs['user_id']=='service-status-probe'
