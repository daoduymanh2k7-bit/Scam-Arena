import json
from pathlib import Path
import pytest
from app.arena.practice_catalog import documents,case_variables,render,FAMILIES
from app.arena.practice_selector import choose
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
    assert 400<kinds.count('benign')<600
    assert any(kinds[i]==kinds[i+1] for i in range(len(kinds)-1))


def test_recency_reduces_selection_without_forcing_alternation():
    rows=[dict(scenario_id=i,scenario_kind='benign',difficulty=1,selection_weight=1) for i in range(3)]
    picked=[choose(rows,[0,0,0],1,str(seed))['scenario_id'] for seed in range(1000)]
    assert picked.count(0)<100
    assert picked.count(1)>300 and picked.count(2)>300
