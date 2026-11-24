import random
from app.arena.practice_catalog import FAMILIES


def choose(rows, recent, level, seed):
    rng=random.Random(seed)
    # Pick truth class first: adding many variants must not skew the true/false ratio.
    kinds=sorted({row['scenario_kind'] for row in rows})
    kind=rng.choice(kinds)
    pool=[r for r in rows if r['scenario_kind']==kind]
    distances=[abs(r['difficulty']-level) for r in pool]
    best=min(distances)
    pool=[r for r in pool if abs(r['difficulty']-level)==best]
    weights=[]
    for row in pool:
        weight=float(row['selection_weight'])
        weight*=0.15 if recent and row['scenario_id']==recent[0] else 1
        weight/=1+recent.count(row['scenario_id'])
        weights.append(weight)
    return rng.choices(pool,weights=weights,k=1)[0]


def select(cursor,user_id,family,difficulty,seed):
    if family!='any' and family not in FAMILIES: raise ValueError('Chủ đề không hợp lệ.')
    cursor.execute("""SELECT s.scenario_id,s.scenario_name,s.selection_weight,v.version_id,
                              v.definition->>'scenario_kind' AS scenario_kind,
                              CASE v.definition->'payload'->>'difficulty' WHEN 'advanced' THEN 3 WHEN 'intermediate' THEN 2 ELSE 1 END AS difficulty
                       FROM scenarios s JOIN scenario_versions v ON v.version_id=s.active_version_id
                       WHERE s.status='published' AND s.scenario_name LIKE 'practice-%%'
                         AND (%s='any' OR v.definition->>'family'=%s) ORDER BY s.scenario_id""",(family,family))
    rows=cursor.fetchall()
    if not rows: raise ValueError('Chưa có kịch bản đã duyệt cho chủ đề này.')
    if {r['scenario_kind'] for r in rows}!={'benign','fraud'}:
        raise ValueError('Chủ đề cần có cả cuộc gọi bình thường và giả mạo đang mở để chọn cân bằng.')
    cursor.execute('SELECT scenario_id FROM call_sessions WHERE user_id=%s ORDER BY started_at DESC LIMIT 12',(user_id,))
    recent=[r['scenario_id'] for r in cursor.fetchall()]
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
    selected=choose(rows,recent,level,seed).copy()
    selected['_selection']={'policy':'mixed-v1','candidates':rows,'recent':recent,'level':level}
    return selected,level
