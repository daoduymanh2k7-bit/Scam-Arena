"""Disposable database and real CPU model integration check; no paid API calls."""
import os
import secrets
from unittest.mock import patch
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from app import database,auth
from app.arena import line_generator as lg,semantic_cache as semantic,call_service


def run():
    admin=psycopg.connect(os.environ['DATABASE_URL'],autocommit=True)
    original=database.DATABASE_URL
    name='arena_semantic_'+secrets.token_hex(5)
    created=False
    try:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)));created=True
        config=conninfo_to_dict(os.environ['DATABASE_URL']);config['dbname']=name
        database.DATABASE_URL=make_conninfo(**config);database.initialize_database()
        semantic.warmup()
        assert semantic._model is not None,'Semantic model must be downloaded for this integration check'
        user,_=auth.register('semantic-fixture','fixture-only-password')
        session=call_service.start_call('practice-delivery-ordinary-1',user['user_id'],'call')
        with database.get_connection_pool().connection() as c:
            node=c.execute("""SELECT n.node_id,n.scenario_id,l.line_text FROM dialogue_nodes n
                 JOIN dialogue_lines l USING(node_id) WHERE n.scenario_id=(SELECT scenario_id FROM call_sessions WHERE session_id=%s)
                 AND NOT n.is_terminal AND l.source='fixed' AND NOT l.is_reprompt ORDER BY n.node_id,l.line_id LIMIT 1""",(session.session_id,)).fetchone()
        args=dict(scenario_id=node['scenario_id'],session_id=session.session_id,target_node=node['node_id'],
                  intent='comply',fixed_text=node['line_text'],is_reprompt=False)
        def resolve(text,**extra):return lg.resolve_bot_line(**args,user_text_masked=text,original_user_text=text,context={'interaction_mode':'call',**extra})
        with patch.object(lg,'_config',return_value=(True,True,'fixture','semantic-test',5,1)),patch.object(lg,'_request_line',return_value=node['line_text']) as generate:
            first=resolve('Tôi đồng ý tiếp tục cuộc gọi')
            assert first.source=='llm',first
            same=resolve('Tôi chấp nhận tiếp tục cuộc gọi')
            assert same.source=='cache_semantic' and same.line_id==first.line_id,same
            assert generate.call_count==1
            opposite=resolve('Tôi không đồng ý tiếp tục cuộc gọi')
            assert generate.call_count==2,opposite
            changed=resolve('Tôi chấp nhận tiếp tục cuộc gọi',case_facts={'place':'a different location'})
            assert generate.call_count==3,changed
            with patch.object(lg,'memory_context',return_value={'conversation_summary':'A different earlier conversation'}):
                memory=resolve('Tôi chấp nhận tiếp tục cuộc gọi')
            assert generate.call_count==4 and memory.source=='llm',memory
            with database.get_connection_pool().connection() as c:
                c.execute('UPDATE dialogue_lines SET preference_score=-1 WHERE line_id=%s',(first.line_id,))
            rejected=resolve('Tôi chấp nhận tiếp tục cuộc gọi')
            assert generate.call_count==5,rejected
        print('PASS: real pretrained model and PostgreSQL reuse paraphrase without API call; negation, changed facts, conversation memory and downvoted replies do not reuse it')
    finally:
        database.close_database();database.DATABASE_URL=original
        if created:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()


if __name__=='__main__':run()
