"""Verify old-table to unified-queue migration in an isolated PostgreSQL database."""
import os
import secrets
from types import SimpleNamespace
from unittest.mock import patch
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from app import database,auth
from app.arena import call_service as calls,data_review as bot,compact_schema
from app.arena.intent_detector import Intent
from app.arena.line_generator import LineResult


def run():
    name='scam_arena_compact_check_'+secrets.token_hex(6)
    original=database.DATABASE_URL
    admin=psycopg.connect(os.environ['DATABASE_URL'],autocommit=True)
    try:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        config=conninfo_to_dict(os.environ['DATABASE_URL']);config['dbname']=name
        database.DATABASE_URL=make_conninfo(**config)
        database.initialize_database();pool=database.get_connection_pool()
        user,_=auth.register('compact-learner',secrets.token_urlsafe(20))
        sessions=[]
        for text in ['Một câu chưa rõ','Một câu đã duyệt','Một câu bị bỏ qua']:
            sid=calls.start_call('bank',user['user_id'],'message').session_id;sessions.append(sid)
            with patch.object(calls,'detect_intent',return_value=SimpleNamespace(intent=Intent.UNKNOWN,matched_rule=None)), \
                 patch.object(calls,'reclassify_unknown',return_value=None), \
                 patch.object(calls,'resolve_bot_line',side_effect=lambda **kw:LineResult(kw['fixed_text'],None,'fixed',0)):
                calls.submit_turn(sid,text,1,user['user_id'])
        run_id,_=bot.create_run();bot.scan(run_id)
        with pool.connection() as c:
            c.execute("UPDATE intent_review_candidates SET review_status='approved' WHERE session_id=%s",(sessions[1],))
            c.execute("UPDATE intent_review_candidates SET review_status='rejected' WHERE session_id=%s",(sessions[2],))
            candidate=c.execute("SELECT * FROM data_review_items WHERE candidate_data->>'session_id'=%s",(str(sessions[1]),)).fetchone()
            c.execute("INSERT INTO reviewed_utterances(turn_id,corrected_text,intent,review_item_id) VALUES(%s,'Bản hiệu chỉnh đã duyệt','doubt',%s)",(candidate['candidate_turn_id'],candidate['item_id']))
            before=c.execute('SELECT * FROM intent_review_candidates ORDER BY candidate_id').fetchall()
            turn_count=c.execute('SELECT count(*) n FROM call_turns').fetchone()['n']
            # Reconstruct the previous physical queue and unused voice tables.
            c.execute('CREATE TABLE legacy_queue_fixture AS SELECT * FROM intent_review_candidates')
            c.execute('DROP VIEW intent_review_candidates')
            c.execute('ALTER TABLE legacy_queue_fixture RENAME TO intent_review_candidates')
            c.execute('UPDATE data_review_items SET candidate_data=NULL,candidate_turn_id=NULL')
            c.execute("CREATE TABLE voice_recordings(recording_id bigint PRIMARY KEY); CREATE TABLE voice_samples(sample_id bigint PRIMARY KEY,recording_id bigint REFERENCES voice_recordings(recording_id),audio bytea); INSERT INTO voice_recordings VALUES(1); INSERT INTO voice_samples VALUES(1,1,decode('010203','hex'))")
            compact_schema.install(c)
            after=c.execute('SELECT * FROM intent_review_candidates ORDER BY candidate_id').fetchall()
            assert before==after,(before,after)
            assert c.execute("SELECT relkind FROM pg_class WHERE oid='intent_review_candidates'::regclass").fetchone()['relkind']=='v'
            assert c.execute("SELECT to_regclass('voice_samples') gone").fetchone()['gone'] is None
            assert c.execute('SELECT count(*) n FROM call_turns').fetchone()['n']==turn_count
            assert c.execute('SELECT review_item_id FROM reviewed_utterances').fetchone()['review_item_id']==candidate['item_id']
        database.initialize_database();database.initialize_database()
        # Both old API writes and the review bot now operate on the same physical rows.
        calls.flag_turn_for_review(sessions[0],1,user['user_id']);calls.flag_turn_for_review(sessions[0],1,user['user_id'])
        run2,_=bot.create_run()
        bot.scan(run2)
        with pool.connection() as c:
            assert c.execute('SELECT count(*) n FROM intent_review_candidates').fetchone()['n']==3
            assert c.execute('SELECT count(*) n FROM data_review_items WHERE candidate_data IS NOT NULL').fetchone()['n']==3
            c.execute("UPDATE intent_review_candidates SET suggested_intent='doubt',confidence=.8,analysis_status='analyzed' WHERE session_id=%s",(sessions[0],))
            item=c.execute("SELECT * FROM data_review_items WHERE candidate_data->>'session_id'=%s",(str(sessions[0]),)).fetchone()
            assert item['suggestion']['intent']=='doubt' and item['analysis_status']=='ready'
            c.execute("UPDATE data_review_items SET decision='rejected' WHERE item_id=%s",(item['item_id'],))
            assert c.execute('SELECT review_status FROM intent_review_candidates WHERE session_id=%s',(sessions[0],)).fetchone()['review_status']=='rejected'
        print('PASS: legacy migration, writable compatibility view, preserved candidate IDs/status/suggestions, curated sample references, original turns, restart idempotency, retired voice tables and shared review state')
    finally:
        if database._pool:database._pool.close();database._pool=None
        database.DATABASE_URL=original
        admin.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s',(name,))
        admin.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(name)))
        admin.close()


if __name__=='__main__':run()
