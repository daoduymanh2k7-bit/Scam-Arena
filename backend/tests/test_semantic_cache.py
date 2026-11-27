from app.arena import semantic_cache as sc
from app.arena.normalization import normalize_phrase
import pytest


class Model:
    def embed(self,texts,**kwargs):
        for text in texts:
            yield [1.,0.] if 'xa' not in text else [0.,1.]


@pytest.fixture(autouse=True)
def model(monkeypatch):
    monkeypatch.setenv('SEMANTIC_CACHE_ENABLED','true')
    monkeypatch.setattr(sc,'_model',Model())
    monkeypatch.setattr(sc,'_vectors',sc.OrderedDict())


def row(text,**kwargs):
    return dict(line_id=1,player_text_norm=normalize_phrase(text),player_text_sample=text,preference_score=0,**kwargs)


def test_paraphrase_reuses_stored_line_without_literal_match():
    original='Tôi không muốn tiếp tục cuộc gọi'
    paraphrase='Tôi không muốn nói chuyện tiếp'
    r=row(original)
    assert sc.match(paraphrase,[r],'refuse') is r


@pytest.mark.parametrize('text,intent',[
    ('Tôi muốn tiếp tục cuộc gọi','refuse'),
    ('Tôi không muốn tiếp tục cuộc gọi','unknown'),
    ('Tôi không muốn tiếp tục cuộc gọi','verify'),
    ('Tôi chuyển 500 nghìn cho bạn','comply'),
    ('Nếu tôi đồng ý thì sao','comply'),
    ('Tôi sẽ đọc mã này','comply'),
    ('Được rồi','comply'),
    ('Tôi gặp sự cố gì vậy','doubt'),
])
def test_unsafe_similarity_never_reuses(text,intent):
    assert sc.match(text,[row('Tôi không muốn tiếp tục cuộc gọi')],intent) is None


def test_rejected_low_similarity_and_downvoted_rows():
    assert sc.match('Tôi đang ở rất xa',[row('Tôi đồng ý tiếp tục cuộc gọi')],'comply') is None
    r=row('Tôi không muốn tiếp tục cuộc gọi');r['preference_score']=-1
    assert sc.match('Tôi không muốn nói chuyện tiếp',[r],'refuse') is None


def test_model_not_ready_disabled_and_busy_fail_open(monkeypatch):
    text='Tôi không muốn tiếp tục cuộc gọi';r=row(text)
    monkeypatch.setattr(sc,'_model',None)
    assert sc.match(text,[r],'refuse') is None
    monkeypatch.setattr(sc,'_model',Model())
    sc._lock.acquire()
    try:assert sc.match(text,[r],'refuse') is None
    finally:sc._lock.release()
    monkeypatch.setenv('SEMANTIC_CACHE_ENABLED','false')
    assert sc.match(text,[r],'refuse') is None


def test_colloquial_and_double_negation_are_not_treated_as_positive():
    assert sc.signature('Tôi ko muốn tiếp tục cuộc gọi')!=sc.signature('Tôi muốn tiếp tục cuộc gọi')
    assert sc.signature('Tôi không thể không tiếp tục cuộc gọi') is None
