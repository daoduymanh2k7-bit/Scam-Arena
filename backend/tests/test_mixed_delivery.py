import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.practice_routes import router
from app.auth import get_current_user
from app.arena.scenario_loader import _load_one, ScenarioLoadError


def test_delivery_pair_has_matching_context_but_distinct_ground_truth():
    root=Path(__file__).resolve().parents[2]/'data/scenarios'
    ordinary=_load_one(json.loads((root/'delivery-ordinary.json').read_text(encoding='utf-8')),'test')
    impostor=_load_one(json.loads((root/'delivery-impostor.json').read_text(encoding='utf-8')),'test')
    assert ordinary.user_context==impostor.user_context
    assert ordinary.stages[0].opening_line==impostor.stages[0].opening_line
    assert ordinary.scenario_kind=='benign' and not ordinary.red_flags
    assert impostor.scenario_kind=='fraud' and impostor.red_flags
    raw=impostor.model_dump(mode='json');raw['red_flags']=[]
    with pytest.raises(ScenarioLoadError): _load_one(raw,'test')


def test_practice_actions_require_authentication():
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        for path,payload in [('check-order',{}),('judge',{'judgement':'benign'})]:
            assert client.post('/api/practice/00000000-0000-0000-0000-000000000001/'+path,json=payload).status_code==401


def test_non_admin_cannot_view_or_publish_practice_catalog():
    app=FastAPI();app.include_router(router)
    app.dependency_overrides[get_current_user]=lambda:{'user_id':'test','role':'user'}
    with TestClient(app) as client:
        for path in ['report','reviews','catalog','drafts']:
            assert client.get('/api/practice/admin/'+path).status_code==403
        assert client.post('/api/practice/admin/validate',json={'document':{}}).status_code==403
        assert client.post('/api/practice/admin/drafts',json={'document':{}}).status_code==403
        assert client.post('/api/practice/admin/reviews',json={'document':{}}).status_code==403
        assert client.post('/api/practice/admin/reviews/1/approve').status_code==403
        assert client.post('/api/practice/admin/catalog/1/selection',json={'enabled':False,'weight':1}).status_code==403
