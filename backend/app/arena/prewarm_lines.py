"""Prewarm generated line pools for a published scenario."""
import argparse, os
from app.database import get_connection_pool, initialize_database
from app.arena.line_generator import _request_line, validate_line

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--scenario',required=True); parser.add_argument('--per-pool',type=int)
    args=parser.parse_args(); pool=args.per_pool or int(os.getenv('LINE_POOL_SIZE','5'))
    initialize_database()
    quota_exhausted=False
    with get_connection_pool().connection() as c,c.cursor() as cur:
        cur.execute("SELECT scenario_id,payload FROM scenarios WHERE scenario_name=%s AND status='published'",(args.scenario,)); s=cur.fetchone()
        if not s: raise SystemExit('Published scenario not found')
        cur.execute("""SELECT n.node_id,line.line_text AS text,n.requested_action,n.objective,n.tactic
                       FROM dialogue_nodes n JOIN dialogue_lines line ON line.node_id=n.node_id
                         AND line.source='fixed' AND line.is_reprompt=FALSE
                       WHERE n.scenario_id=%s AND NOT n.is_terminal""",(s['scenario_id'],)); nodes=cur.fetchall()
        for node in nodes:
            cur.execute("SELECT DISTINCT t.intent FROM dialogue_transitions t WHERE t.to_node_id=%s",(node['node_id'],)); intents={r['intent'] for r in cur.fetchall()} | {'unknown'}
            for intent in intents:
                for reprompt in ((False, True) if intent == 'unknown' else (False,)):
                    cur.execute("SELECT count(*) AS n FROM dialogue_lines WHERE node_id=%s AND intent=%s AND is_reprompt=%s AND source='llm' AND prompt_version=%s AND enabled",(node['node_id'],intent,reprompt,os.getenv('LINE_PROMPT_VERSION','v2'))); count=cur.fetchone()['n']
                    missing=max(0,pool-count)
                    for _ in range(missing):
                        context={'persona':s['payload'].get('persona',{}),'user_context':s['payload'].get('user_context',''),
                          'objective':node['objective'],'tactics':[node['tactic']] if node['tactic'] else [],'requested_action':node['requested_action'],
                          'sample_line':node['text'],'intent':intent,'player_text':'Tôi cần xác minh thông tin.','recent_turns':[]}
                        try:
                            # Pre-warm runs offline and can wait longer than live turns.
                            timeout=max(20.0,float(os.getenv('LINE_LLM_TIMEOUT_SECONDS','3')))
                            line=validate_line(_request_line(context,os.getenv('GEMINI_MODEL','gemini-2.5-flash'),timeout),context['player_text'])
                        except Exception as exc:
                            print(f'Prewarm stopped for {args.scenario}/{node["node_id"]}/{intent}: {str(exc)[:350]}')
                            if '429' in str(exc) or 'quota' in str(exc).lower() or 'resource_exhausted' in str(exc).lower():
                                quota_exhausted=True
                            break
                        if not line: break
                        with get_connection_pool().connection() as insert_conn,insert_conn.cursor() as insert_cur:
                            insert_cur.execute("INSERT INTO dialogue_lines(node_id,intent,is_reprompt,player_text_norm,line_text,source,model,prompt_version) VALUES(%s,%s,%s,NULL,%s,'llm',%s,%s) ON CONFLICT DO NOTHING RETURNING line_id",(node['node_id'],intent,reprompt,line,context.get('_generated_model',os.getenv('GEMINI_MODEL','gemini-2.5-flash')),os.getenv('LINE_PROMPT_VERSION','v2')))
                            if not insert_cur.fetchone(): break
                    if quota_exhausted: return
if __name__=='__main__': main()
