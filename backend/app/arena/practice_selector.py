import random
from app.arena.practice_catalog import FAMILIES


FRAUD_PROBABILITY = 0.75
SELECTION_POLICY = 'mixed-v2-class-cycles'


def choose(rows, recent, level, seed, seen_counts=None, *, policy=SELECTION_POLICY):
    rng=random.Random(seed)
    # Pick truth class first: adding many variants must not skew the true/false ratio.
    kinds=sorted({row['scenario_kind'] for row in rows})
    kind=(rng.choice(kinds) if policy=='mixed-v1' else
          ('fraud' if rng.random()<FRAUD_PROBABILITY else 'benign') if len(kinds)==2 else kinds[0])
    pool=[r for r in rows if r['scenario_kind']==kind]
    distances=[abs(r['difficulty']-level) for r in pool]
    best=min(distances)
    pool=[r for r in pool if abs(r['difficulty']-level)==best]
    # Lifetime counts keep rotation intact beyond the 12-call recency window.
    # JSON replay snapshots use string keys; callers may supply integer keys.
    if policy!='mixed-v1':
        counts={str(key):int(value) for key,value in (seen_counts or {}).items()}
        least_seen=min(counts.get(str(row['scenario_id']),0) for row in pool)
        pool=[row for row in pool if counts.get(str(row['scenario_id']),0)==least_seen]
    weights=[]
    for row in pool:
        weight=float(row['selection_weight'])
        weight*=0.15 if recent and row['scenario_id']==recent[0] else 1
        weight/=1+recent.count(row['scenario_id'])
        weights.append(weight)
    return rng.choices(pool,weights=weights,k=1)[0]


def replay_selection(snapshot, seed):
    policy=snapshot['policy']
    if policy not in {'mixed-v1',SELECTION_POLICY}:
        raise ValueError('Không hỗ trợ phiên bản chọn kịch bản này.')
    return choose(snapshot['candidates'],snapshot['recent'],snapshot['level'],seed,
                  snapshot.get('seen_counts'),policy=policy)


def select(cursor,user_id,family,difficulty,seed):
    if family!='any' and family not in FAMILIES: raise ValueError('Chủ đề không hợp lệ.')
    # Serialize selection until start_call commits the new session, including
    # two tabs starting calls simultaneously on the same account.
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",('practice-selection:'+str(user_id),))
    cursor.execute("""SELECT s.scenario_id,s.scenario_name,s.selection_weight,v.version_id,
                              v.definition->>'scenario_kind' AS scenario_kind,
                              CASE v.definition->'payload'->>'difficulty' WHEN 'advanced' THEN 3 WHEN 'intermediate' THEN 2 ELSE 1 END AS difficulty
                       FROM scenarios s JOIN scenario_versions v ON v.version_id=s.active_version_id
                       WHERE s.status='published' AND v.status='published' AND s.scenario_name LIKE 'practice-%%'
                         AND (%s='any' OR v.definition->>'family'=%s) ORDER BY s.scenario_id""",(family,family))
    rows=cursor.fetchall()
    if not rows: raise ValueError('Chưa có kịch bản đã duyệt cho chủ đề này.')
    if {r['scenario_kind'] for r in rows}!={'benign','fraud'}:
        raise ValueError('Chủ đề cần có cả cuộc gọi bình thường và giả mạo đang mở để chọn ngẫu nhiên.')
    cursor.execute('SELECT scenario_id FROM call_sessions WHERE user_id=%s ORDER BY started_at DESC LIMIT 12',(user_id,))
    recent=[r['scenario_id'] for r in cursor.fetchall()]
    cursor.execute('''SELECT scenario_id,count(*) AS seen_count FROM call_sessions
                      WHERE user_id=%s AND scenario_id=ANY(%s) GROUP BY scenario_id''',
                   (user_id,[row['scenario_id'] for row in rows]))
    seen_counts={str(row['scenario_id']):row['seen_count'] for row in cursor.fetchall()}
    level={'beginner':1,'intermediate':2,'advanced':3}.get(difficulty,1)
    if difficulty=='adaptive':
        cursor.execute("""SELECT (j.judgement=v.definition->>'scenario_kind' AND NOT EXISTS(
                              SELECT 1 FROM practice_events e WHERE e.session_id=cs.session_id
                              AND e.event_type IN ('open_requested_link','share_demo_code'))) AS correct
                           FROM practice_judgements j JOIN call_sessions cs USING(session_id)
                           JOIN scenario_versions v ON v.version_id=cs.scenario_version_id
                           WHERE cs.user_id=%s ORDER BY j.created_at DESC LIMIT 10""",(user_id,))
        results=cursor.fetchall()
        if len(results)>=5:
            accuracy=sum(r['correct'] for r in results)/len(results)
            level=3 if accuracy>=0.8 else 2 if accuracy>=0.5 else 1
    selected=choose(rows,recent,level,seed,seen_counts).copy()
    selected['_selection']={'policy':SELECTION_POLICY,'fraud_probability':FRAUD_PROBABILITY,
                            'candidates':rows,'recent':recent,'level':level,'seen_counts':seen_counts}
    return selected,level
