from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.user_admin_routes import router
from app.auth import get_current_user


def test_user_administration_requires_login():
    app=FastAPI();app.include_router(router)
    with TestClient(app) as c:
        assert c.get('/api/admin/users').status_code==401
        assert c.get('/api/admin/users/any/events').status_code==401
        assert c.post('/api/admin/users/any/status',json={'locked':True,'expected_locked':False,'reason':'test'}).status_code==401


def test_normal_user_cannot_read_accounts_or_change_status():
    app=FastAPI();app.include_router(router)
    app.dependency_overrides[get_current_user]=lambda:{'user_id':'user','role':'user'}
    with TestClient(app) as c:
        assert c.get('/api/admin/users').status_code==403
        assert c.get('/api/admin/users/any/events').status_code==403
        assert c.post('/api/admin/users/any/status',json={'locked':True,'expected_locked':False,'reason':'test'}).status_code==403
