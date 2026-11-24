"""Integration check in a disposable PostgreSQL database, never in the live catalog.

Run inside the app container: python backend/tools/check_scenario_versions.py
Requires CREATEDB permission. Uses DATABASE_URL without printing credentials.
"""
import copy
import json
import os
import secrets
from types import SimpleNamespace
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app import database
from app.arena import call_service as calls
from app.arena.intent_detector import Intent
from app.arena.line_generator import LineResult
from app.arena.scenario_versions import publish_document


def run():
    name = 'scam_arena_versions_check_' + secrets.token_hex(6)
    original_url = database.DATABASE_URL
    config = conninfo_to_dict(os.environ['DATABASE_URL'])
    admin = psycopg.connect(os.environ['DATABASE_URL'], autocommit=True)
    created = False
    try:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        created = True
        config['dbname'] = name
        database.DATABASE_URL = make_conninfo(**config)
        database.initialize_database()
        pool = database.get_connection_pool()
        with pool.connection() as c:
            user = c.execute("INSERT INTO app_users(username,password_hash) VALUES('version-check','test-only') RETURNING user_id").fetchone()['user_id']
        old = calls.start_call('bank', user, 'call')
        raw = json.loads((database.ROOT / 'data/scenarios/bank.json').read_text(encoding='utf-8'))
        raw = copy.deepcopy(raw)
        raw['version'] += 1
        raw['title'] += ' — test revision'
        raw['stages'][0]['opening_line'] = 'Đây là lời mở đầu của phiên bản thử nghiệm mới.'
        raw['scoring']['rules'].append({'intent':'refuse','stage_id':'intro','points_delta':-3,
                                       'feedback':'Điểm thử nghiệm theo phiên bản mới.', 'critical':False})
        with pool.connection() as c, c.cursor() as cur:
            vid = publish_document(cur, raw)
        with pool.connection() as c, c.cursor() as cur:
            assert publish_document(cur, raw) == vid
            assert c.execute('SELECT count(*) AS n FROM scenario_versions WHERE scenario_id=(SELECT scenario_id FROM scenarios WHERE scenario_name=%s)', ('bank',)).fetchone()['n'] == 2
        new = calls.start_call('bank', user, 'call')
        assert old.scenario_title != new.scenario_title
        assert new.bot_text == raw['stages'][0]['opening_line']
        from app.api.practice_routes import check_order, judge, Judgement
        ordinary=calls.start_call('delivery-ordinary',user,'call')
        check_order(ordinary.session_id,{'user_id':user})
        check_order(ordinary.session_id,{'user_id':user})
        with patch.object(calls,'detect_intent',return_value=SimpleNamespace(intent=Intent.COMPLY,matched_rule='test')), \
             patch.object(calls,'resolve_bot_line',side_effect=lambda **kw: LineResult(kw['fixed_text'],None,'fixed',0)):
            for _ in range(2):
                normal=calls.submit_turn(ordinary.session_id,'Tôi nhận ở sảnh.',2,user)
                assert normal.score_delta==0
        assert normal.ended and normal.outcome=='safe'
        evaluation=judge(ordinary.session_id,Judgement(judgement='benign'),{'user_id':user})
        assert evaluation['correct'] and evaluation['checked_order']
        assert calls.get_call_summary(ordinary.session_id,user).total_score==evaluation['evaluation_score']
        assert judge(ordinary.session_id,Judgement(judgement='fraud'),{'user_id':user})['judgement']=='benign'
        with pool.connection() as c:
            assert c.execute('SELECT count(*) AS n FROM practice_events WHERE session_id=%s',(ordinary.session_id,)).fetchone()['n']==1
        mixed=calls.start_call('mixed-delivery',user,'call')
        assert mixed.scenario_key=='mixed-delivery' and mixed.scenario_title=='Cuộc gọi dịch vụ'
        from app.arena.practice_selector import replay_selection
        with pool.connection() as c:
            saved=c.execute('SELECT random_seed,world_state,scenario_id FROM call_sessions WHERE session_id=%s',(mixed.session_id,)).fetchone()
            trace=saved['world_state']['selection']
            assert trace['fraud_probability']==0.75
            assert replay_selection(trace,saved['random_seed'])['scenario_id']==saved['scenario_id']
        # Exercise persisted rotation beyond the old 12-call memory window.
        with pool.connection() as c:
            rotation_user=c.execute("INSERT INTO app_users(username,password_hash) VALUES('rotation-check','test-only') RETURNING user_id").fetchone()['user_id']
        cycles={'fraud':[],'benign':[]}
        for index in range(40):
            with patch.object(calls,'session_seed',return_value='rotation-'+str(index)):
                rotation=calls.start_call('mixed-any',rotation_user,'call','beginner')
            with pool.connection() as c:
                saved=c.execute('SELECT random_seed,world_state,scenario_id FROM call_sessions WHERE session_id=%s',(rotation.session_id,)).fetchone()
                trace=saved['world_state']['selection']
                assert replay_selection(trace,saved['random_seed'])['scenario_id']==saved['scenario_id']
                actual={str(row['scenario_id']):row['n'] for row in c.execute(
                    'SELECT scenario_id,count(*) AS n FROM call_sessions WHERE user_id=%s AND session_id<>%s GROUP BY scenario_id',
                    (rotation_user,rotation.session_id)).fetchall()}
                assert trace['seen_counts']==actual
                selected=next(row for row in trace['candidates'] if row['scenario_id']==saved['scenario_id'])
                cycles[selected['scenario_kind']].append(saved['scenario_id'])
            calls.finish_call(rotation.session_id,rotation_user)
        for history in cycles.values():
            for index in range(0,len(history)-2,3):
                assert len(set(history[index:index+3]))==3
        # Concurrent tabs must observe each other's committed selections.
        from concurrent.futures import ThreadPoolExecutor
        with pool.connection() as c:
            parallel_user=c.execute("INSERT INTO app_users(username,password_hash) VALUES('parallel-rotation-check','test-only') RETURNING user_id").fetchone()['user_id']
        with patch.object(calls,'session_seed',return_value='rotation-0'), ThreadPoolExecutor(max_workers=2) as executor:
            parallel=list(executor.map(lambda _: calls.start_call('mixed-any',parallel_user,'call','beginner'),range(2)))
        with pool.connection() as c:
            chosen=c.execute('SELECT DISTINCT scenario_id FROM call_sessions WHERE user_id=%s',(parallel_user,)).fetchall()
            assert len(chosen)==2
        for family in ['appointment','support','any']:
            call=calls.start_call('mixed-'+family,user,'call','advanced','assessment')
            assert call.practice_context and '{' not in call.bot_text
            calls.finish_call(call.session_id,user)
        from app.api.practice_routes import Event,record_event,propose,Review,decide,report,context
        from fastapi import HTTPException
        service=calls.start_call('practice-appointment-impostor-2',user,'call')
        try:
            record_event(service.session_id,Event(event_type='open_requested_link'),{'user_id':user})
        except HTTPException as exc: assert exc.status_code==409
        else: raise AssertionError('Action accepted before request')
        with patch.object(calls,'detect_intent',return_value=SimpleNamespace(intent=Intent.COMPLY,matched_rule='test')), \
             patch.object(calls,'resolve_bot_line',side_effect=lambda **kw: LineResult(kw['fixed_text'],None,'fixed',0)):
            for _ in range(2): calls.submit_turn(service.session_id,'Tôi muốn nghe giải thích.',2,user)
        assert 'open_requested_link' in context(service.session_id,{'user_id':user})['actions']
        record_event(service.session_id,Event(event_type='open_requested_link'),{'user_id':user})
        calls.finish_call(service.session_id,user)
        assert judge(service.session_id,Judgement(judgement='fraud'),{'user_id':user})['risk_action_recorded']
        from app.api.inbox_routes import inbox, read as read_message, resend
        from app.arena.notifications import brief
        mailbox=calls.start_call('practice-support-ordinary-1',user,'call')
        owner={'user_id':user}
        messages=inbox(mailbox.session_id,owner)['messages']
        assert len(messages)==1 and messages[0]['channel']=='email'
        assert mailbox.practice_context
        assert inbox(mailbox.session_id,owner)['messages'][0]['message_id']==messages[0]['message_id']
        read_message(mailbox.session_id,messages[0]['message_id'],owner)
        assert inbox(mailbox.session_id,owner)['messages'][0]['read_at']
        for operation in [lambda:inbox(mailbox.session_id,{'user_id':None}),
                          lambda:read_message(old.session_id,messages[0]['message_id'],owner),
                          lambda:resend(mailbox.session_id,owner)]:
            try: operation()
            except HTTPException as exc: assert exc.status_code in (404,409)
            else: raise AssertionError('Invalid inbox access/action accepted')
        with pool.connection() as c:
            c.execute("UPDATE call_sessions SET current_node_id=(SELECT node_id FROM dialogue_nodes WHERE scenario_version_id=%s AND requested_action='share_sensitive' LIMIT 1) WHERE session_id=%s",(vid,new.session_id))
        first_code=inbox(new.session_id,owner)['messages'][0]
        assert len(first_code['code'])==6 and first_code['expires_at']>first_code['created_at']
        assert len(inbox(new.session_id,owner)['messages'])==1
        try: resend(new.session_id,owner)
        except HTTPException as exc: assert exc.status_code==429
        else: raise AssertionError('Resend cooldown bypassed')
        for _ in range(2):
            with pool.connection() as c:
                c.execute("UPDATE practice_messages SET created_at=now()-interval '30 seconds' WHERE session_id=%s",(new.session_id,))
            resend(new.session_id,owner)
        codes=inbox(new.session_id,owner)['messages']
        assert len(codes)==3 and not codes[0]['revoked_at'] and all(m['revoked_at'] for m in codes[1:])
        with pool.connection() as c,c.cursor() as cur:
            assert all(set(m)=={'channel','subject'} for m in brief(cur,new.session_id))
        try: resend(new.session_id,owner)
        except HTTPException as exc: assert exc.status_code==429
        else: raise AssertionError('Resend limit bypassed')
        calls.finish_call(new.session_id,user)
        assert not inbox(new.session_id,owner)['can_resend']
        # Keep the earlier version-isolation exercise active below.
        new=calls.start_call('bank',user,'call')
        # Reproduce short location replies with no external LLM calls.
        with patch.object(calls,'detect_intent',return_value=SimpleNamespace(intent=Intent.UNKNOWN,matched_rule=None)), \
             patch.object(calls,'reclassify_unknown',return_value=None) as reclassify, \
             patch.object(calls,'resolve_bot_line',side_effect=lambda **kw: LineResult(kw['fixed_text'],None,'fixed',0)) as generate:
            for family,text in [('delivery','Ở sảnh đi'),('appointment','Đúng lịch nhé'),('support','Mở ứng dụng là bị thoát.')]:
                closed=calls.start_call(f'practice-{family}-ordinary-1',user,'call')
                reclassify.reset_mock();generate.reset_mock()
                result=calls.submit_turn(closed.session_id,text,2,user)
                assert result.ended and result.outcome=='safe' and result.intent_method=='rule'
                assert 'kết thúc cuộc gọi' in result.bot_text
                assert not reclassify.called and not generate.called
                with pool.connection() as c:
                    persisted=c.execute('SELECT ended_at,world_state,n.is_terminal FROM call_sessions cs JOIN dialogue_nodes n ON n.node_id=cs.current_node_id WHERE session_id=%s',(closed.session_id,)).fetchone()
                    assert persisted['ended_at'] and persisted['is_terminal'] and persisted['world_state']['service_completion']
                try: calls.submit_turn(closed.session_id,text,2,user)
                except ValueError: pass
                else: raise AssertionError('Accepted speech after the service call ended')
            for scenario,text in [('practice-delivery-ordinary-1','Ở sảnh được không?'),('practice-delivery-impostor-1','Ở sảnh đi')]:
                active=calls.start_call(scenario,user,'call')
                assert not calls.submit_turn(active.session_id,text,2,user).ended
        admin_user={'user_id':user,'role':'admin'}
        with pool.connection() as c:
            submitted=c.execute("SELECT definition->'document' AS doc FROM scenario_versions WHERE version_id=(SELECT active_version_id FROM scenarios WHERE scenario_name='practice-support-ordinary-1')").fetchone()['doc']
        submitted['version']+=1;submitted['stages'][0]['opening_line']='Tôi gọi để trao đổi về phiếu hỗ trợ của anh/chị.'
        from app.api.practice_routes import save_draft,drafts,Draft,validate_preview
        before_versions=None
        with pool.connection() as c:
            before_versions=c.execute('SELECT count(*) AS n FROM scenario_versions').fetchone()['n']
        saved_draft=save_draft(Draft(document={'title':'Unfinished editor draft'}),admin_user)
        assert drafts(admin_user)[0]['document']=={'title':'Unfinished editor draft'}
        updated_draft=save_draft(Draft(document=submitted,draft_id=saved_draft['draft_id'],expected_revision=1),admin_user)
        assert updated_draft['revision']==2
        try: save_draft(Draft(document={},draft_id=saved_draft['draft_id'],expected_revision=1),admin_user)
        except HTTPException as exc: assert exc.status_code==409
        else: raise AssertionError('Stale draft overwrote newer content')
        with pool.connection() as c:
            other=c.execute("INSERT INTO app_users(username,password_hash) VALUES('another-admin-check','test') RETURNING user_id").fetchone()['user_id']
        assert drafts({'user_id':other,'role':'admin'})==[]
        try: save_draft(Draft(document={},draft_id=saved_draft['draft_id'],expected_revision=2),{'user_id':other,'role':'admin'})
        except HTTPException as exc: assert exc.status_code==404
        else: raise AssertionError('Another admin overwrote a private draft')
        assert validate_preview(Review(document=submitted),admin_user)['valid']
        with pool.connection() as c:
            assert c.execute('SELECT count(*) AS n FROM scenario_versions').fetchone()['n']==before_versions
        pending=propose(Review(document=submitted),admin_user)
        published=decide(pending['review_id'],'approve',admin_user)
        assert published['version_id']
        try: decide(pending['review_id'],'approve',admin_user)
        except HTTPException as exc: assert exc.status_code==409
        else: raise AssertionError('Duplicate review accepted')
        assert report(admin_user)['classification']
        bounded=calls.start_call('practice-support-ordinary-2',user,'call')
        with patch.object(calls,'resolve_bot_line',side_effect=lambda **kw: LineResult(kw['fixed_text'],None,'fixed',0)):
            for index in range(12):
                intention=Intent.VERIFY if index%2 else Intent.COMPLY
                with patch.object(calls,'detect_intent',return_value=SimpleNamespace(intent=intention,matched_rule='test')):
                    bounded_turn=calls.submit_turn(bounded.session_id,'Tôi muốn tiếp tục đối chiếu.',2,user)
                if bounded_turn.ended: break
        assert bounded_turn.ended and bounded_turn.turn_no==12
        custom=copy.deepcopy(submitted);custom['id']='practice-editor-created-check';custom['version']=1
        custom_review=propose(Review(document=custom),admin_user)
        assert decide(custom_review['review_id'],'approve',admin_user)['version_id']
        custom_call=calls.start_call(custom['id'],user,'call')
        assert custom_call.session_id and custom_call.practice_context
        from app.api.practice_routes import configure_selection,Selection
        with pool.connection() as c:
            configurable=c.execute("SELECT scenario_id FROM scenarios WHERE scenario_name='practice-support-ordinary-1'").fetchone()['scenario_id']
        configure_selection(configurable,Selection(enabled=False,weight=2),admin_user)
        for _ in range(5):
            example=calls.start_call('practice-delivery-ordinary-1',user,'call')
            calls.finish_call(example.session_id,user)
            judge(example.session_id,Judgement(judgement='benign'),{'user_id':user})
        adaptive=calls.start_call('mixed-any',user,'call','adaptive')
        with pool.connection() as c:
            assert c.execute('SELECT world_state FROM call_sessions WHERE session_id=%s',(adaptive.session_id,)).fetchone()['world_state']['selection']['level']==3
        try: context(adaptive.session_id,{'user_id':'not-the-owner'})
        except HTTPException as exc: assert exc.status_code==404
        else: raise AssertionError('Another user could inspect the case')
        with patch.object(calls,'detect_intent',return_value=SimpleNamespace(intent=Intent.REFUSE,matched_rule='test')), \
             patch.object(calls,'resolve_bot_line',side_effect=lambda **kw: LineResult(kw['fixed_text'],None,'fixed',0)):
            first = calls.submit_turn(old.session_id, 'Tôi không đồng ý.', 2, user)
            second = calls.submit_turn(new.session_id, 'Tôi không đồng ý.', 2, user)
        assert first.score_delta != -3 and second.score_delta == -3
        assert calls.get_call_transcript(old.session_id,user).scenario_title == old.scenario_title
        calls.get_call_summary(old.session_id,user)
        calls.list_admin_scenario_graphs()
        calls.list_call_history(10,user)
        calls.finish_call(old.session_id,user)
        with pool.connection() as c:
            row = c.execute('SELECT s.scenario_version_id,n.scenario_version_id AS terminal_version FROM call_sessions s JOIN dialogue_nodes n ON n.node_id=s.current_node_id WHERE session_id=%s', (old.session_id,)).fetchone()
            assert row['scenario_version_id'] == row['terminal_version'] != vid
            state = c.execute('SELECT version_id,content_hash FROM scenario_versions ORDER BY version_id').fetchall()
        for statement in ["UPDATE scenario_versions SET definition='{}' WHERE version_id=%s",
                          "UPDATE dialogue_nodes SET objective='changed' WHERE scenario_version_id=%s"]:
            try:
                with pool.connection() as c: c.execute(statement,(vid,))
            except psycopg.errors.RaiseException:
                pass
            else:
                raise AssertionError('Published data was mutable')
        database.close_database()
        database.initialize_database()
        with database.get_connection_pool().connection() as c:
            assert c.execute('SELECT version_id,content_hash FROM scenario_versions ORDER BY version_id').fetchall() == state
        print('PASS: migration/restart, version isolation, all families, seed replay, adaptive difficulty, evidence idempotency, risk-event gating, owner privacy, frozen judgement, admin publication/rejection settings and immutable definitions')
    finally:
        database.close_database()
        database.DATABASE_URL = original_url
        if created:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()


if __name__ == '__main__':
    run()
