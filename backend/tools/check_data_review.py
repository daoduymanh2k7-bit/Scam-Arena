"""Exercise the review bot in a disposable PostgreSQL database, with fake LLM calls."""
import json
import os
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import database,auth
from app.api import data_review_routes as routes
from app.arena import data_review as bot,call_service as calls
from app.arena.intent_detector import Intent
from app.arena.line_generator import LineResult


def run():
    name='scam_arena_review_check_'+secrets.token_hex(6)
    original=database.DATABASE_URL;admin=psycopg.connect(os.environ['DATABASE_URL'],autocommit=True);created=False
    try:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)));created=True
        config=conninfo_to_dict(os.environ['DATABASE_URL']);config['dbname']=name;database.DATABASE_URL=make_conninfo(**config)
        database.initialize_database();database.initialize_database();pool=database.get_connection_pool()
        actor,token=auth.register('review-admin',secrets.token_urlsafe(20))
        learner,learner_token=auth.register('review-learner',secrets.token_urlsafe(20))
        with pool.connection() as c:c.execute("UPDATE app_users SET role='admin' WHERE user_id=%s",(actor['user_id'],))
        def utterance(text):
            sid=calls.start_call('bank',learner['user_id'],'message').session_id
            with patch.object(calls,'detect_intent',return_value=SimpleNamespace(intent=Intent.UNKNOWN,matched_rule=None)),\
                 patch.object(calls,'reclassify_unknown',return_value=None),\
                 patch.object(calls,'resolve_bot_line',side_effect=lambda **kw:LineResult(kw['fixed_text'],None,'fixed',0)):
                calls.submit_turn(sid,text,1,learner['user_id'])
            return sid
        sid=utterance('Tôi ko tham za chương trình đó')
        old=calls.start_call('bank',learner['user_id'],'message')
        active=calls.start_call('bank',learner['user_id'],'message')
        with pool.connection() as c:
            c.execute("UPDATE call_sessions SET started_at=now()-interval '2 days' WHERE session_id=ANY(%s::uuid[])",([str(old.session_id),str(active.session_id)],))
        def fake(context):
            assert context['review_kind'] in {'intent','rule'}
            assert 'session_id' not in context and 'turn_id' not in context
            return {'intent':'doubt','corrected_text':'Tôi không tham gia chương trình đó.',
                    'confidence':.8,'needs_audio':False,'rationale':'Phủ nhận việc tham gia, không phải xác minh độc lập.',
                    'provider':'test','model':'message-test','prompt_version':'data-review-v1'}
        app=FastAPI();app.include_router(routes.router)
        with TestClient(app) as client:
            assert client.get('/api/admin/data-review').status_code==401
            client.cookies.set(auth.COOKIE_NAME,learner_token)
            assert client.get('/api/admin/data-review').status_code==403
            client.cookies.set(auth.COOKIE_NAME,token)
            assert client.post('/api/admin/data-review/run',json={'limit':21}).status_code==422
            with patch.object(bot,'request_review',side_effect=fake) as llm:
                first,started=bot.create_run(actor['user_id']);assert started
                same,started=bot.create_run(actor['user_id']);assert not started and same==first
                bot.run_review(first,limit=1)
                with pool.connection() as c:
                    state=c.execute("SELECT status,stats FROM data_review_runs WHERE run_id=%s",(first,)).fetchone()
                assert state["status"]=="completed",state
                assert llm.call_count==1
                second,started=bot.create_run(actor['user_id']);assert started
                bot.run_review(second,limit=20)
            queue=client.get('/api/admin/data-review?decision=all').json()
            assert queue['run']['status']=='completed'
            intent=next(item for item in queue['items'] if item['kind']=='intent' and item['original']['session_id']==str(sid))
            def decision(item,**overrides):
                return client.post(f"/api/admin/data-review/items/{item['item_id']}/decision",json={
                    'decision':'accepted','expected_hash':item['source_hash'],**overrides})
            assert decision(intent,expected_hash='0'*64).status_code==409
            accepted=decision(intent,intent='doubt',corrected_text='Tôi không tham gia chương trình đó.');assert accepted.status_code==200,accepted.text
            assert decision(intent).status_code==409
            with pool.connection() as c:
                turn=c.execute('SELECT user_text_masked FROM call_turns WHERE session_id=%s',(sid,)).fetchone()
                assert turn['user_text_masked']=='Tôi ko tham za chương trình đó'
                fixed=c.execute('SELECT * FROM reviewed_utterances WHERE turn_id=%s',(intent['original']['turn_id'],)).fetchone()
                assert fixed['corrected_text']=='Tôi không tham gia chương trình đó.'
                rule_count=c.execute('SELECT count(*) n FROM intent_phrase_rules').fetchone()['n']
            # Accepting a corrected sample does not create a broad contains rule.
            with pool.connection() as c:assert c.execute('SELECT count(*) n FROM intent_phrase_rules').fetchone()['n']==rule_count
            rule=next(item for item in queue['items'] if item['kind']=='rule')
            result=decision(rule,intent='doubt');assert result.status_code==200,result.text
            assert decision(rule).status_code==409
            stale=next(item for item in queue['items'] if item['kind']=='stale_session' and item['source_key']==str(old.session_id))
            assert decision(stale).status_code==200
            with pool.connection() as c:
                state=c.execute('SELECT ended_at,abandoned_at FROM call_sessions WHERE session_id=%s',(old.session_id,)).fetchone()
                assert state['abandoned_at'] and not state['ended_at']
            try:calls.submit_turn(old.session_id,'Xin chào',1,learner['user_id'])
            except ValueError:pass
            else:raise AssertionError('Abandoned session accepted a new turn')
            calls.finish_call(old.session_id,learner['user_id'])
            assert next(row for row in calls.list_call_history(100,learner['user_id']) if row.session_id==str(old.session_id)).abandoned
            with pool.connection() as c:assert c.execute('SELECT ended_at FROM call_sessions WHERE session_id=%s',(old.session_id,)).fetchone()['ended_at'] is None
            stale=next(item for item in queue['items'] if item['kind']=='stale_session' and item['source_key']==str(active.session_id))
            with pool.connection() as c:c.execute('UPDATE call_sessions SET started_at=now() WHERE session_id=%s',(active.session_id,))
            assert decision(stale).status_code==409
            # Existing approvals outside this screen make a proposal stale.
            stale_sid=utterance('Không, tôi chưa biết gì cả')
            third,_=bot.create_run(actor['user_id'])
            with patch.object(bot,'request_review',side_effect=fake):bot.run_review(third,20)
            items=client.get('/api/admin/data-review?decision=all').json()['items']
            item=next(row for row in items if row['kind']=='intent' and row['original']['session_id']==str(stale_sid))
            with pool.connection() as c:c.execute("UPDATE intent_review_candidates SET review_status='rejected' WHERE candidate_id=%s",(int(item['source_key']),))
            assert decision(item).status_code==409
            # Duplicate review touches only queue status, never the source turns.
            duplicate_sids=[utterance('Hai bản chờ có cùng nội dung') for _ in range(2)]
            with pool.connection() as c:
                c.execute("UPDATE intent_review_candidates SET caller_text='Cùng một câu hỏi về giao dịch' WHERE session_id=ANY(%s::uuid[])",([str(sid) for sid in duplicate_sids],))
                before=c.execute('SELECT count(*) n FROM call_turns').fetchone()['n']
            duplicate_run,_=bot.create_run(actor['user_id'])
            with patch.object(bot,'request_review',side_effect=fake):bot.run_review(duplicate_run,2)
            with pool.connection() as c:
                duplicate=c.execute("SELECT * FROM data_review_items WHERE kind='duplicate' ORDER BY item_id DESC LIMIT 1").fetchone()
            assert decision(duplicate).status_code==200
            with pool.connection() as c:
                assert c.execute('SELECT count(*) n FROM call_turns').fetchone()['n']==before
                states=c.execute('SELECT review_status FROM intent_review_candidates WHERE session_id=ANY(%s::uuid[])',([str(sid) for sid in duplicate_sids],)).fetchall()
                assert sorted(row['review_status'] for row in states)==['pending','rejected']
            # Unclear audio is not silently promoted into a training label.
            unclear_sid=utterance('Một câu cần nghe lại')
            unclear_run,_=bot.create_run(actor['user_id'])
            with patch.object(bot,'request_review',return_value={**fake({'review_kind':'intent'}),'needs_audio':True}):bot.run_review(unclear_run,1,unclear_sid)
            with pool.connection() as c:
                unclear=c.execute("SELECT * FROM data_review_items WHERE kind='intent' AND original->>'session_id'=%s",(str(unclear_sid),)).fetchone()
            assert decision(unclear).status_code==409
            assert decision(unclear,intent='unknown').status_code==200
            with pool.connection() as c:
                assert not c.execute('SELECT 1 FROM reviewed_utterances WHERE turn_id=%s',(unclear['original']['turn_id'],)).fetchone()
            # Failures are bounded and never store provider error strings/secrets.
            failed_sid=utterance('Đây là câu cần xem lại')
            fourth,_=bot.create_run(actor['user_id'])
            with patch.object(bot,'request_review',side_effect=RuntimeError('SECRET_FAKE_KEY')):bot.run_review(fourth,2,failed_sid)
            failed=client.get('/api/admin/data-review?decision=all').json()
            assert 'SECRET_FAKE_KEY' not in json.dumps(failed)
            assert any(row['analysis_status']=='failed' for row in failed['items'])
            # A restart/interrupted worker can be recovered by the next scan.
            stuck,_=bot.create_run(actor['user_id'])
            with pool.connection() as c:c.execute("UPDATE data_review_runs SET updated_at=now()-interval '11 minutes' WHERE run_id=%s",(stuck,))
            replacement,started=bot.create_run(actor['user_id']);assert started and replacement!=stuck
            with patch.object(bot,'request_review',side_effect=fake):bot.run_review(replacement,2)
            from rasa.evaluation.dataset_workflow import collect
            with TemporaryDirectory() as tmp:
                collect(Path(tmp));review=json.loads((Path(tmp)/'review.json').read_text())
                assert any(row['text']=='Tôi không tham gia chương trình đó.' and row['intent']=='doubt' for row in review['rows'])
            with pool.connection() as c:c.execute('UPDATE app_users SET is_locked=true WHERE user_id=%s',(actor['user_id'],))
            assert client.get('/api/admin/data-review').status_code==401
        print('PASS: review migration/restart, admin access, bounded message LLM, idempotent scans, corrections without overwriting originals, rule approval, stale protection, abandoned sessions, failure redaction, recovery and curated Rasa collection')
    finally:
        database.close_database();database.DATABASE_URL=original
        if created:
            admin.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s',(name,))
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        admin.close()


if __name__=='__main__':run()
