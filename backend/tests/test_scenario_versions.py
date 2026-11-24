from app.arena.scenario_versions import digest, session_seed


def test_graph_digest_is_canonical_but_changes_with_rules():
    first = {'title':'Mô phỏng', 'rule':{'score':10,'intent':'verify'}}
    reordered = {'rule':{'intent':'verify','score':10}, 'title':'Mô phỏng'}
    assert digest(first) == digest(reordered)
    assert digest(first) != digest({'title':'Mô phỏng','rule':{'score':-10,'intent':'verify'}})


def test_session_seeds_are_independent():
    seeds = {session_seed() for _ in range(100)}
    assert len(seeds) == 100
    assert all(len(seed)==32 for seed in seeds)
