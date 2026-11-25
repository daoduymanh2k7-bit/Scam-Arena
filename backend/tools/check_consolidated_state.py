"""Non-empty legacy session/document migration and post-migration behavior checks."""
import os,secrets
from types import SimpleNamespace
from unittest.mock import patch
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from psycopg.types.json import Jsonb
from app import database,auth
from app.arena import call_service as calls,conversation_memory as memory,consolidated_state
from app.arena.intent_detector import Intent
from app.arena.line_generator import LineResult
from app.api.practice_routes import save_draft,Draft


def run():
    name='scam_arena_state_check_'+secrets.token_hex(6)
    original=database.DATABASE_URL;admin=psycopg.connect(os.environ['DATABASE_URL'],autocommit=True)
    try:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        config=conninfo_to_dict(os.environ['DATABASE_URL']);config['dbname']=name
        database.DATABASE_URL=make_conninfo(**config);database.initialize_database();pool=database.get_connection_pool()
        user,_=auth.register('state-learner',secrets.token_urlsafe(20));uid=user['user_id']
        sid=calls.start_call('bank',uid,'message').session_id
        with patch.object(calls,'detect_intent',return_value=SimpleNamespace(intent=Intent.UNKNOWN,matched_rule=None)), \
             patch.object(calls,'reclassify_unknown',return_value=None), \
             patch.object(calls,'resolve_bot_line',side_effect=lambda **kw:LineResult(kw['fixed_text'],None,'fixed',0)):
            calls.submit_turn(sid,'Một câu chưa rõ',1,uid);calls.submit_turn(sid,'Một câu khác',1,uid)
        with pool.connection() as c:
            c.execute("""UPDATE call_sessions SET memory_text='Người chơi muốn xác minh.',memory_covered_turn=1,memory_max_words=150,
                memory_word_count=6,memory_provider='test',memory_updated_at=now(),practice_judgement='uncertain',
                judgement_reason='Cần kiểm tra lại',judgement_evaluation='{"correct":false}',judged_at=now() WHERE session_id=%s""",(sid,))
            c.execute("INSERT INTO scenario_documents(document_kind,document_id,creator_id,document,status,revision) VALUES('draft',1,%s,%s,'draft',3),('review',1,%s,%s,'pending',1)",(uid,Jsonb({'title':'Bản nháp'}),uid,Jsonb({'title':'Bản duyệt'})))
            names=['conversation_memories','practice_judgements','practice_admin_drafts','practice_reviews']
            before={table:c.execute('SELECT * FROM '+table).fetchall() for table in names}
            for table in names:
                c.execute(sql.SQL('CREATE TABLE {} AS SELECT * FROM {}').format(sql.Identifier('legacy_'+table),sql.Identifier(table)))
                c.execute(sql.SQL('DROP VIEW {}').format(sql.Identifier(table)))
                c.execute(sql.SQL('ALTER TABLE {} RENAME TO {}').format(sql.Identifier('legacy_'+table),sql.Identifier(table)))
            c.execute('DROP TABLE scenario_documents')
            c.execute("UPDATE call_sessions SET memory_text=NULL,memory_covered_turn=NULL,memory_max_words=NULL,memory_word_count=NULL,memory_provider=NULL,memory_updated_at=NULL,practice_judgement=NULL,judged_at=NULL,judgement_reason='',judgement_evaluation=NULL")
            consolidated_state.install(c)
            for table in names:
                assert c.execute('SELECT * FROM '+table).fetchall()==before[table],table
                assert c.execute('SELECT relkind FROM pg_class WHERE oid=%s::regclass',(table,)).fetchone()['relkind']=='v'
        database.initialize_database();database.initialize_database()
        with patch.object(memory,'request_summary',return_value=('Người chơi vẫn muốn xác minh.','test')):
            memory.update_summary(sid,uid,force=True)
        assert memory.read_memory(sid,uid)['covered_turn']==2
        with pool.connection() as c:c.execute('UPDATE call_sessions SET memory_covered_turn=1 WHERE session_id=%s',(sid,))
        def invalidated_during_request(*args):
            with pool.connection() as c:memory.invalidate_memory(c,sid)
            return 'Không được ghi bản tóm tắt lỗi thời.','test'
        with patch.object(memory,'request_summary',side_effect=invalidated_during_request):
            memory.update_summary(sid,uid,force=True)
        assert memory.read_memory(sid,uid)['covered_turn']==0
        with pool.connection() as c:memory.invalidate_memory(c,sid)
        assert memory.read_memory(sid,uid)['covered_turn']==0
        saved=save_draft(Draft(document={'title':'Bản sửa'},draft_id=1,expected_revision=3),{'user_id':uid})
        assert saved['revision']==4
        new=save_draft(Draft(document={'title':'Bản mới'}),{'user_id':uid})
        assert new['draft_id']>1
        print('PASS: non-empty summaries/judgements/drafts/reviews, colliding old document IDs, timestamps and payloads preserved, restart idempotency, summary CAS/invalidation and draft ownership/revisions')
    finally:
        if database._pool:database._pool.close();database._pool=None
        database.DATABASE_URL=original
        admin.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s',(name,))
        admin.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(name)));admin.close()


if __name__=='__main__':run()
