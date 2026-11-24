"""Verify account administration in an isolated database; no production account changes."""
import os,secrets
from concurrent.futures import ThreadPoolExecutor
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from app import database,auth
from app.api import user_admin_routes as users,auth_routes
from app.arena import call_service
from app.api.practice_routes import judge,Judgement


def run():
    original=database.DATABASE_URL
    admin=psycopg.connect(os.environ['DATABASE_URL'],autocommit=True)
    name='arena_user_check_'+secrets.token_hex(6)
    created=False
    try:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)));created=True
        config=conninfo_to_dict(os.environ['DATABASE_URL']);config['dbname']=name
        database.DATABASE_URL=make_conninfo(**config);database.initialize_database()
        pool=database.get_connection_pool();password='local-fixture-only-password'
        one,token1=auth.register('manager-one',password)
        two,token2=auth.register('manager-two',password)
        person,old_token=auth.register('learner-check',password)
        with pool.connection() as c:
            c.execute("UPDATE app_users SET role='admin' WHERE user_id IN (%s,%s)",(one['user_id'],two['user_id']))
        one['role']=two['role']='admin'
        app=FastAPI();app.include_router(users.router);app.include_router(auth_routes.router)
        with TestClient(app) as client:
            assert client.get('/api/admin/users').status_code==401
            client.cookies.set(auth.COOKIE_NAME,old_token)
            assert client.get('/api/admin/users').status_code==403
            client.cookies.set(auth.COOKIE_NAME,token1)
            page=client.get('/api/admin/users',params={'page_size':1}).json()
            assert page['total']==3 and len(page['users'])==1
            assert client.get('/api/admin/users',params={'search':'%'}).json()['total']==0
            assert 'password_hash' not in str(page) and 'token_hash' not in str(page)
            sid=person['user_id']
            for _ in range(2):
                session=call_service.start_call('practice-delivery-ordinary-1',sid,'call')
                call_service.finish_call(session.session_id,sid)
            assessment=judge(session.session_id,Judgement(judgement='benign'),{'user_id':sid})
            stats=client.get('/api/admin/users',params={'search':'learner-check'}).json()['users'][0]
            assert stats['sessions']==2 and stats['finished']==2 and stats['reviewed']==1 and stats['correct']==1
            assert float(stats['avg_score'])==assessment['evaluation_score']
            assert client.post('/api/admin/users/'+one['user_id']+'/status',json={'locked':True,'expected_locked':False,'reason':'self-lock test'}).status_code==409
            path='/api/admin/users/'+sid+'/status'
            assert client.post(path,json={'locked':True,'expected_locked':False,'reason':'Fixture lock'}).status_code==200
            assert client.get('/api/admin/users',params={'state':'locked'}).json()['total']==1
            try:auth.get_current_user(token=old_token)
            except HTTPException as e:assert e.status_code==401
            else:raise AssertionError('Locked cookie retained access')
            try:auth.login('learner-check',password)
            except ValueError:pass
            else:raise AssertionError('Locked account signed in')
            assert client.post(path,json={'locked':False,'expected_locked':False}).status_code==409
            assert client.post(path,json={'locked':False,'expected_locked':True,'reason':'Fixture unlock'}).status_code==200
            events=client.get('/api/admin/users/'+sid+'/events').json()
            assert [e['action'] for e in events]==['unlock','lock']
            _,new_token=auth.login('learner-check',password)
            assert auth.get_current_user(token=new_token)['user_id']==sid
            try:auth.get_current_user(token=old_token)
            except HTTPException:pass
            else:raise AssertionError('Unlock restored a revoked cookie')
        def lock_other(actor,target):
            try:users.change_status(target['user_id'],users.AccountStatus(locked=True,expected_locked=False,reason='Concurrent fixture lock'),actor);return 200
            except HTTPException as e:return e.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda pair:lock_other(*pair),[(one,two),(two,one)]))
        assert sorted(results)==[200,403],results
        with pool.connection() as c:
            assert c.execute("SELECT count(*) AS n FROM app_users WHERE role='admin' AND NOT is_locked").fetchone()['n']==1
            surviving=c.execute("SELECT user_id,username,role FROM app_users WHERE role='admin' AND NOT is_locked").fetchone()
            blocked=c.execute("SELECT user_id,username,role FROM app_users WHERE role='admin' AND is_locked").fetchone()
        try:users.change_status(person['user_id'],users.AccountStatus(locked=True,expected_locked=False,reason='Revoked admin attempt'),blocked)
        except HTTPException as e:assert e.status_code==403
        else:raise AssertionError('Revoked admin modified another account')
        database.close_database();database.initialize_database()
        assert users.list_users(search='learner-check',state='all',role='all',page=1,page_size=25,user=surviving)['total']==1
        assert len(users.user_events(person['user_id'],surviving))==2
        print('PASS: account migration/restart, admin-only access, literal search/pagination, aggregates without private content, lock/login/cookie revocation, unlock, audit history, stale-state protection and concurrent last-admin safety')
    finally:
        database.close_database();database.DATABASE_URL=original
        if created:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()


if __name__=='__main__':run()
