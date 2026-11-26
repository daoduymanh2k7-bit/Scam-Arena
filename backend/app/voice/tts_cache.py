"""Bounded private in-process audio cache and single-flight synthesis."""
from collections import OrderedDict
from concurrent.futures import Future
import threading
import time


class AudioCache:
    def __init__(self,max_bytes=32*1024*1024,ttl=600,clock=time.monotonic):
        self.max_bytes=max_bytes;self.ttl=ttl;self.clock=clock
        self.entries=OrderedDict();self.pending={};self.size=0;self.lock=threading.Lock()

    def get(self,key,build):
        with self.lock:
            for old,(expiry,data) in list(self.entries.items()):
                if expiry<=self.clock():self.size-=len(data);del self.entries[old]
            if key in self.entries:
                _,data=self.entries[key];self.entries.move_to_end(key);return data,True
            future=self.pending.get(key)
            owner=future is None
            if owner:future=Future();self.pending[key]=future
        if not owner:return future.result(),True
        try:
            data=build()
            with self.lock:
                if len(data)<=self.max_bytes:
                    while self.entries and self.size+len(data)>self.max_bytes:
                        _,(_,old)=self.entries.popitem(last=False);self.size-=len(old)
                    self.entries[key]=(self.clock()+self.ttl,data);self.size+=len(data)
                self.pending.pop(key,None);future.set_result(data)
            return data,False
        except BaseException as exc:
            with self.lock:self.pending.pop(key,None);future.set_exception(exc)
            raise


def sentence_chunks(text):
    """Only segment complete, already validated text; never decode partial model tokens."""
    import re
    normalized=re.sub(r'\s+',' ',text).strip()
    if len(normalized)<160:return [text]
    # Avoid splitting abbreviations, decimals or lists where punctuation is ambiguous.
    if re.search(r'\d[.]\d|\b[A-ZĐ]{2,}[.]|\b(?:Mr|Ms|Dr)[.]',text):return [text]
    parts=re.split(r'(?<=[.!?])\s+',normalized)
    result=[];pending=''
    for part in parts:
        pending=(pending+' '+part).strip()
        if len(pending)>=72 and len(result)<2:
            result.append(pending);pending=''
    if pending:
        if result and len(pending)<40:result[-1]+=' '+pending
        else:result.append(pending)
    return result or [text]
