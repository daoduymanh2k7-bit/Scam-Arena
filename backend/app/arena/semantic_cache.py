"""Conservative paraphrase matching; models warm off the conversation request path."""
import logging
import math
import os
import re
import threading
from collections import OrderedDict
from app.arena.normalization import normalize_phrase

log=logging.getLogger(__name__)
_model=None
_lock=threading.Lock()
_vectors=OrderedDict()
MODEL='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'


def enabled():
    return os.getenv('SEMANTIC_CACHE_ENABLED','true').lower() in {'1','true'}


def warmup():
    global _model
    if not enabled():return
    try:
        from fastembed import TextEmbedding
        model=TextEmbedding(model_name=MODEL,threads=1,
            cache_dir=os.path.join(os.getenv('HF_HOME','/models/huggingface'),'semantic'))
        list(model.embed(['Xin chào'],batch_size=1))
        with _lock:_model=model
    except Exception:
        log.warning('Semantic model unavailable; exact matching and contextual generation remain available')


def signature(text):
    norm=normalize_phrase(text)
    # Short acknowledgements, questions, conditions, numbers and deictic references need context.
    if len(norm.split())<4 or len(norm)>200 or re.search(r'\d|\[|\*',text):return None
    tokens=set(norm.split())
    if tokens & {'neu','hay','chua','nay','do','kia','sao','gi','dau','ai','nao','bao','ma','otp'}:return None
    negative={'khong','ko','k','hong','chang','dung'}
    if sum(word in negative for word in norm.split())>1:return None
    return (bool(tokens & negative),frozenset(tokens & {'tien','ngan','hang','cong','an'}))


def _vector(text):
    if text in _vectors:
        _vectors.move_to_end(text)
        return _vectors[text]
    raw=next(iter(_model.embed([text],batch_size=1)))
    length=math.sqrt(sum(float(x)*float(x) for x in raw))
    if not length:raise ValueError('empty embedding')
    vector=tuple(float(x)/length for x in raw)
    _vectors[text]=vector
    while len(_vectors)>1024:_vectors.popitem(last=False)
    return vector


def match(text,rows,intent):
    # This matcher never changes the player's intent or scenario transition.
    if not enabled() or _model is None or intent not in {'refuse','comply','doubt','hang_up'}:return None
    guard=signature(text)
    if guard is None:return None
    candidates=[r for r in rows[:128] if r.get('preference_score',0)>=0 and r.get('player_text_norm')
                and signature(r.get('player_text_sample') or r['player_text_norm'])==guard]
    if not candidates or not _lock.acquire(blocking=False):return None
    try:
        query=_vector(text)
        threshold=max(.90,min(.99,float(os.getenv('SEMANTIC_CACHE_THRESHOLD','.93'))))
        best=None;score=threshold
        for row in candidates:
            candidate=_vector(row.get('player_text_sample') or row['player_text_norm'])
            cosine=sum(a*b for a,b in zip(query,candidate))
            if cosine>=score:best=row;score=cosine
        return best
    except Exception:
        log.warning('Semantic lookup skipped; generating a context-aware response')
        return None
    finally:_lock.release()
