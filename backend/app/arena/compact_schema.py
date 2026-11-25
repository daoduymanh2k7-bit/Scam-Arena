"""Consolidate the review queue; keep a writable compatibility view, not duplicate storage.

Back up the database before first rollout. The VPS deployment script does this before startup.
"""
import json
from psycopg.types.json import Jsonb


def install(cursor):
    cursor.execute("""ALTER TABLE data_review_items ADD COLUMN IF NOT EXISTS candidate_data JSONB;
        ALTER TABLE data_review_items ADD COLUMN IF NOT EXISTS candidate_turn_id BIGINT REFERENCES call_turns(turn_id) ON DELETE CASCADE;
        CREATE UNIQUE INDEX IF NOT EXISTS review_candidate_turn ON data_review_items(candidate_turn_id) WHERE candidate_turn_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS review_candidate_key ON data_review_items(source_key) WHERE candidate_data IS NOT NULL;
        CREATE SEQUENCE IF NOT EXISTS review_candidate_id_seq;""")
    relation=cursor.execute("SELECT relkind FROM pg_class WHERE oid=to_regclass('public.intent_review_candidates')").fetchone()
    if relation and relation['relkind']=='r':
        cursor.execute('LOCK TABLE intent_review_candidates IN ACCESS EXCLUSIVE MODE')
        rows=cursor.execute('SELECT * FROM intent_review_candidates ORDER BY candidate_id').fetchall()
        for row in rows:
            key=str(row['candidate_id'])
            decision={'pending':'pending','approved':'accepted','rejected':'rejected'}[row['review_status']]
            existing=cursor.execute("""SELECT item_id FROM data_review_items WHERE kind='intent' AND source_key=%s
                AND decision=%s ORDER BY item_id DESC LIMIT 1""",(key,decision)).fetchone()
            metadata={k:row[k] for k in ('session_id','scenario_id','stage','requested_action','caller_text','user_text_masked','detected_intent','source_reason')}
            metadata=json.loads(json.dumps(metadata,default=str))
            if existing:
                item_id=existing['item_id']
            else:
                original={**metadata,'candidate_id':row['candidate_id'],'turn_id':row['turn_id'],'player_text':row['user_text_masked']}
                from app.arena.data_review import fingerprint
                suggestion={k:row[k] for k in ('suggested_intent','suggested_phrase','confidence','rationale') if row[k] is not None}
                suggestion['intent']=suggestion.pop('suggested_intent',None)
                item_id=cursor.execute("""INSERT INTO data_review_items(kind,source_key,source_hash,original,suggestion,analysis_status,decision,created_at,reviewed_at)
                    VALUES('intent',%s,%s,%s,%s,%s,%s,%s,%s) RETURNING item_id""",
                    (key,fingerprint(original),Jsonb(original),Jsonb(suggestion),'ready' if row['analysis_status']=='analyzed' else row['analysis_status'],decision,row['created_at'],row['reviewed_at'])).fetchone()['item_id']
            metadata['legacy_created_at']=row['created_at'].isoformat()
            suggestion={'intent':row['suggested_intent'],'suggested_phrase':row['suggested_phrase'],'confidence':row['confidence'],'rationale':row['rationale']}
            cursor.execute('''UPDATE data_review_items SET candidate_data=%s,candidate_turn_id=%s,
                suggestion=suggestion || %s,analysis_status=%s,reviewed_at=%s WHERE item_id=%s''',
                (Jsonb(metadata),row['turn_id'],Jsonb(suggestion),'ready' if row['analysis_status']=='analyzed' else row['analysis_status'],row['reviewed_at'],item_id))
            # Keep prior proposals and their IDs for audit/curated-sample FKs, away from the live source key.
            cursor.execute("""UPDATE data_review_items SET source_key='history:' || source_key || ':' || item_id::text,
                decision=CASE WHEN decision='pending' THEN 'rejected' ELSE decision END,
                result=CASE WHEN decision='pending' THEN '{"action":"superseded_by_unified_queue"}'::jsonb ELSE result END
                WHERE kind='intent' AND source_key=%s AND item_id<>%s""",(key,item_id))
        assert cursor.execute('SELECT count(*) n FROM data_review_items WHERE candidate_data IS NOT NULL').fetchone()['n']==len(rows)
        cursor.execute('DROP TABLE intent_review_candidates')
    if not relation or relation['relkind']=='r':
        cursor.execute("""SELECT setval('review_candidate_id_seq',GREATEST(1,
            COALESCE((SELECT max(source_key::bigint)+1 FROM data_review_items WHERE candidate_data IS NOT NULL),1)),false)""")
    cursor.execute("""CREATE OR REPLACE VIEW intent_review_candidates AS SELECT
        source_key::bigint AS candidate_id,(candidate_data->>'session_id')::uuid AS session_id,
        candidate_turn_id AS turn_id,(candidate_data->>'scenario_id')::bigint AS scenario_id,
        candidate_data->>'stage' AS stage,candidate_data->>'requested_action' AS requested_action,
        candidate_data->>'caller_text' AS caller_text,candidate_data->>'user_text_masked' AS user_text_masked,
        candidate_data->>'detected_intent' AS detected_intent,candidate_data->>'source_reason' AS source_reason,
        suggestion->>'intent' AS suggested_intent,suggestion->>'suggested_phrase' AS suggested_phrase,
        (suggestion->>'confidence')::real AS confidence,suggestion->>'rationale' AS rationale,
        CASE analysis_status WHEN 'ready' THEN 'analyzed' ELSE analysis_status END AS analysis_status,
        CASE decision WHEN 'accepted' THEN 'approved' ELSE decision END AS review_status,
        reviewed_at,COALESCE((candidate_data->>'legacy_created_at')::timestamptz,created_at) AS created_at FROM data_review_items WHERE candidate_data IS NOT NULL;
        CREATE OR REPLACE FUNCTION write_intent_review_view() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE metadata jsonb; item bigint;
        BEGIN
          IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'Review history cannot be deleted through the compatibility view';
          END IF;
          IF TG_OP='INSERT' THEN
            NEW.candidate_id=COALESCE(NEW.candidate_id,nextval('review_candidate_id_seq'));
            NEW.source_reason=COALESCE(NEW.source_reason,'unknown');
            NEW.analysis_status=COALESCE(NEW.analysis_status,'pending');
            NEW.review_status=COALESCE(NEW.review_status,'pending');
            NEW.created_at=COALESCE(NEW.created_at,now());
          END IF;
          IF NEW.session_id IS NULL OR NEW.turn_id IS NULL OR NEW.scenario_id IS NULL OR NEW.stage IS NULL
             OR NEW.requested_action IS NULL OR NEW.caller_text IS NULL OR NEW.user_text_masked IS NULL
             OR NEW.detected_intent IS NULL OR NEW.detected_intent NOT IN ('verify','refuse','doubt','comply','share_sensitive','transfer_money','hang_up','unknown')
             OR NEW.source_reason NOT IN ('unknown','player_flagged')
             OR NEW.analysis_status NOT IN ('pending','analyzed','failed','not_configured')
             OR NEW.review_status NOT IN ('pending','approved','rejected')
             OR NEW.confidence<0 OR NEW.confidence>1 THEN RAISE EXCEPTION 'Invalid review candidate'; END IF;
          metadata=jsonb_build_object('session_id',NEW.session_id,'scenario_id',NEW.scenario_id,'stage',NEW.stage,
            'requested_action',NEW.requested_action,'caller_text',NEW.caller_text,'user_text_masked',NEW.user_text_masked,
            'detected_intent',NEW.detected_intent,'source_reason',NEW.source_reason);
          IF TG_OP='INSERT' THEN
            INSERT INTO data_review_items(kind,source_key,source_hash,original,candidate_data,candidate_turn_id,created_at)
              VALUES('intent',NEW.candidate_id::text,repeat('0',64),metadata || jsonb_build_object('candidate_id',NEW.candidate_id,'session_id',NEW.session_id,'turn_id',NEW.turn_id,'player_text',NEW.user_text_masked),metadata,NEW.turn_id,NEW.created_at)
              RETURNING item_id INTO item;
          ELSE
            IF NEW.candidate_id<>OLD.candidate_id OR NEW.turn_id<>OLD.turn_id OR NEW.session_id<>OLD.session_id THEN
              RAISE EXCEPTION 'Cannot change review identity';
            END IF;
            SELECT item_id INTO item FROM data_review_items WHERE candidate_data IS NOT NULL AND source_key=OLD.candidate_id::text FOR UPDATE;
          END IF;
          UPDATE data_review_items SET candidate_data=COALESCE(candidate_data,'{}'::jsonb) || metadata,
            suggestion=suggestion || jsonb_build_object('intent',NEW.suggested_intent,'suggested_phrase',NEW.suggested_phrase,'confidence',NEW.confidence,'rationale',NEW.rationale),
            analysis_status=CASE NEW.analysis_status WHEN 'analyzed' THEN 'ready' ELSE NEW.analysis_status END,
            decision=CASE NEW.review_status WHEN 'approved' THEN 'accepted' ELSE NEW.review_status END,
            reviewed_at=NEW.reviewed_at,updated_at=now() WHERE item_id=item;
          RETURN NEW;
        END $$;
        DROP TRIGGER IF EXISTS write_intent_review ON intent_review_candidates;
        CREATE TRIGGER write_intent_review INSTEAD OF INSERT OR UPDATE OR DELETE ON intent_review_candidates
          FOR EACH ROW EXECUTE FUNCTION write_intent_review_view();
        DROP TABLE IF EXISTS voice_samples;
        DROP TABLE IF EXISTS voice_recordings;""")
