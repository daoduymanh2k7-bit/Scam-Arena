import json
from pathlib import Path
import pytest
from app.arena.practice_catalog import documents,case_variables,render,FAMILIES
from app.arena.practice_selector import choose, replay_selection
from app.arena.scenario_loader import _load_one,ScenarioLoadError


def test_all_families_have_reviewed_pairs_at_every_level():
    base=json.loads((Path(__file__).resolve().parents[2]/'data/scenarios/bank.json').read_text(encoding='utf-8'))
    docs=list(documents(base));assert len(docs)==18
    for raw in docs:
        doc=_load_one(raw,'bundle')
        assert doc.family in FAMILIES
        assert '{' not in render(doc.stages[0].opening_line,case_variables('seed'))
    for family in FAMILIES:
        for difficulty in ['beginner','intermediate','advanced']:
            pair=[d for d in docs if d['family']==family and d['difficulty']==difficulty]
            assert {d['scenario_kind'] for d in pair}=={'benign','fraud'}
            assert pair[0]['user_context']==pair[1]['user_context']
            assert pair[0]['stages'][0]['opening_line']==pair[1]['stages'][0]['opening_line']
    assert len(next(d for d in docs if d['id']=='practice-support-impostor-3')['stages'])>len(next(d for d in docs if d['id']=='practice-support-impostor-1')['stages'])
    bad=docs[0];bad['stages'][0]['requested_action']='share_sensitive'
    with pytest.raises(ScenarioLoadError): _load_one(bad,'unsafe ordinary')


def test_replay_and_difficulty_and_truth_class_are_stable():
    rows=[dict(scenario_id=i,scenario_kind=kind,difficulty=level,selection_weight=1)
          for i,(kind,level) in enumerate([('benign',1),('fraud',1),('benign',2),('fraud',2)])]
    assert choose(rows,[1],2,'a')==choose(rows,[1],2,'a')
    assert all(choose(rows,[],2,str(seed))['difficulty']==2 for seed in range(100))
    kinds=[choose(rows,[],1,str(seed))['scenario_kind'] for seed in range(1000)]
    assert 700<kinds.count('fraud')<800
    assert any(kinds[i]==kinds[i+1] for i in range(len(kinds)-1))


def test_recency_reduces_selection_without_forcing_alternation():
    rows=[dict(scenario_id=i,scenario_kind='benign',difficulty=1,selection_weight=1) for i in range(3)]
    picked=[choose(rows,[0,0,0],1,str(seed))['scenario_id'] for seed in range(1000)]
    assert picked.count(0)<100
    assert picked.count(1)>300 and picked.count(2)>300


def test_each_truth_class_rotates_without_repeats_until_its_pool_is_covered():
    rows=[dict(scenario_id=i,scenario_kind=kind,difficulty=1,selection_weight=1)
          for i,kind in enumerate(['fraud']*3+['benign']*3)]
    counts={};recent=[];cycles={'fraud':[],'benign':[]}
    for seed in range(400):
        row=choose(rows,recent,1,str(seed),counts)
        key=str(row['scenario_id']);kind=row['scenario_kind']
        cycles[kind].append(row['scenario_id'])
        counts[key]=counts.get(key,0)+1
        recent=([row['scenario_id']]+recent)[:12]
    for history in cycles.values():
        for start in range(0,len(history)-2,3):
            assert len(set(history[start:start+3]))==3
    assert 270<len(cycles['fraud'])<330


def test_new_and_less_seen_scenarios_override_weights_and_old_recency():
    rows=[dict(scenario_id=i,scenario_kind='fraud',difficulty=1,selection_weight=10000 if i==0 else 1)
          for i in range(3)]
    for seed in range(100):
        assert choose(rows,[],1,str(seed),{'0':200,'1':50})['scenario_id']==2
        assert choose(rows,[],1,str(seed),{0:200,1:50,2:50})['scenario_id']!=0


def test_more_fraud_variants_do_not_change_the_class_probability():
    rows=[dict(scenario_id=i,scenario_kind='fraud' if i else 'benign',difficulty=1,selection_weight=1)
          for i in range(100)]
    assert 700<sum(choose(rows,[],1,str(seed))['scenario_kind']=='fraud' for seed in range(1000))<800


def test_counts_survive_json_replay_and_do_not_force_a_different_difficulty():
    rows=[dict(scenario_id=i,scenario_kind=kind,difficulty=level,selection_weight=1)
          for i,(kind,level) in enumerate([('fraud',1),('fraud',2),('benign',1),('benign',2)])]
    counts={0:0,1:10,2:0,3:10}
    for seed in range(50):
        first=choose(rows,[1,3],2,str(seed),counts)
        assert first['difficulty']==2
        assert choose(rows,[1,3],2,str(seed),json.loads(json.dumps(counts)))==first


def test_old_selection_snapshots_keep_the_original_equal_class_replay():
    import random
    rows=[dict(scenario_id=i,scenario_kind=kind,difficulty=1,selection_weight=1)
          for i,kind in enumerate(['benign','fraud'])]
    snapshot={'policy':'mixed-v1','candidates':rows,'recent':[],'level':1}
    for seed in range(100):
        key=str(seed)
        expected=random.Random(key).choice(['benign','fraud'])
        assert replay_selection(snapshot,key)['scenario_kind']==expected


def test_support_calls_provide_the_same_concrete_issue_to_player_caller_and_email():
    from app.arena.practice_catalog import case_spec
    import random
    base=json.loads((Path(__file__).resolve().parents[2]/'data/scenarios/bank.json').read_text(encoding='utf-8'))
    support=[d for d in documents(base) if d['family']=='support']
    assert len(support)==6
    for seed in ['first','second','third']:
        facts=case_variables(seed)
        assert facts==case_variables(seed)
        for doc in support:
            context=render(doc['user_context'],facts)
            opening=render(doc['stages'][0]['opening_line'],facts)
            evidence=render(case_spec({'family':'support','payload':doc})['evidence'],facts)
            assert facts['support_issue'] in context and facts['support_issue'] in opening and facts['support_issue'] in evidence
            assert 'mô tả lại phần đang gặp lỗi' not in opening
            assert '{' not in context+opening+evidence
            assert len(opening)<=300
        # Added facts do not change the original seeded reference/window/place.
        rng=random.Random(seed)
        assert facts['reference']=='DEMO-'+str(rng.randrange(1000,9999))
        assert facts['window']==rng.choice(['chiều nay','sáng mai','trong khung giờ đã hẹn'])
        assert facts['place']==rng.choice(['sảnh tòa nhà','quầy tiếp nhận','điểm hẹn đã ghi trong ứng dụng'])
