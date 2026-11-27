import json
from unittest.mock import patch
from urllib.error import HTTPError
import pytest
from app.arena import line_generator as lg
from app.arena.line_generator import validate_line, cache_key, pick_from_pool
from app.arena.normalization import normalize_phrase

def test_validation():
    assert validate_line('Vâng, tôi hiểu ý anh/chị.')
    for bad in ('Xem https://example.com ngay nhé','Mã 123456 này','Tôi là AI trợ lý','abc','x'*301): assert validate_line(bad) is None
    assert validate_line('Xin chào bạn nhé','Xin chào bạn nhé') is None
    assert validate_line('Tôi hiểu, nhưng anh/chị hãy xác nhận ngay.')
    assert validate_line('Xin chào bạn nhé','xin chào bạn nhé') is None
    for bad in ('email a@b.com nhé','Tôi là mô hình ngôn ngữ','```đoạn mã```','   '): assert validate_line(bad) is None

def test_cache_key():
    assert cache_key('Mã **** đây','Mã 123456 đây') is None
    assert cache_key('Tôi muốn xác minh') == normalize_phrase('Tôi muốn xác minh')

def test_pool_avoids_previous():
    rows=[{'line_id':1,'line_text':'A','use_count':0},{'line_id':2,'line_text':'B','use_count':1}]
    assert pick_from_pool(rows,'A')['line_text']=='B'

def test_pool_prefers_lowest_use_and_handles_single_choice():
    rows=[{'line_id':2,'line_text':'B','use_count':4},{'line_id':1,'line_text':'A','use_count':0}]
    assert pick_from_pool(rows)['line_text']=='A'
    assert pick_from_pool(rows,'A')['line_text']=='B'

def test_feature_off_and_terminal_never_touch_db():
    with patch.dict('os.environ',{'LINE_LLM_ENABLED':'false'}), patch.object(lg,'get_connection_pool',side_effect=AssertionError):
        assert lg.resolve_bot_line(scenario_id=1,session_id='s',target_node=2,intent='unknown',user_text_masked='x',fixed_text='Fixed line.',is_reprompt=False).source=='fixed'
    with patch.dict('os.environ',{'LINE_LLM_ENABLED':'true','GEMINI_API_KEY':'x'}), patch.object(lg,'get_connection_pool',side_effect=AssertionError):
        assert lg.resolve_bot_line(scenario_id=1,session_id='s',target_node=2,intent='unknown',user_text_masked='x',fixed_text='Fixed line.',is_reprompt=False,terminal=True).source=='fixed'

def test_gemini_request_uses_json_and_key_header():
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return b'{"candidates":[{"content":{"parts":[{"text":"{\\"line\\":\\"Xin chao ban nhe.\\"}"}]}}]}'
    with patch.dict('os.environ',{'GEMINI_API_KEY':'fake','GEMINI_MODEL':'gemini-test'}), patch.object(lg,'urlopen',return_value=Response()) as open_url:
        assert lg._request_line({'player_text':'masked'},'gemini-test',1)=='Xin chao ban nhe.'
        req=open_url.call_args.args[0]
        assert req.full_url.endswith('/gemini-test:generateContent')
        assert req.get_header('X-goog-api-key')=='fake'

def test_gemini_json_with_preamble_is_extracted():
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return b'{"candidates":[{"content":{"parts":[{"text":"Here is the JSON: {\\"line\\":\\"Xin chao ban nhe.\\"}"}]}}]}'
    with patch.dict('os.environ',{'GEMINI_API_KEY':'fake'}), patch.object(lg,'urlopen',return_value=Response()):
        assert lg._request_line({'player_text':'masked'},'gemini-test',1)=='Xin chao ban nhe.'

def test_gemini_http_failure_falls_back_to_openrouter():
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return b'{"choices":[{"message":{"content":"{\\"line\\":\\"Xin chao ban nhe.\\"}"}}]}'
    error=HTTPError('https://gemini.test',429,'quota',{},None)
    with patch.dict('os.environ',{'GEMINI_API_KEY':'gemini','OPENROUTER_API_KEY':'router','OPENROUTER_MODEL':'openrouter/free'}), patch.object(lg,'urlopen',side_effect=[error,Response()]) as urlopen:
        assert lg._request_line({'player_text':'masked'},'gemini-test',1)=='Xin chao ban nhe.'
        assert urlopen.call_count==2
        assert 'openrouter.ai/api/v1/chat/completions' in urlopen.call_args.args[0].full_url

def test_openrouter_null_content_fails_cleanly():
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return b'{"choices":[{"message":{"content":null}}]}'
    with patch.dict('os.environ',{'OPENROUTER_API_KEY':'fake'}), patch.object(lg,'urlopen',return_value=Response()):
        with pytest.raises(ValueError,match='no text content'):
            lg._request_openrouter({},1)

def test_groq_failure_uses_openrouter():
    with patch.dict('os.environ',{'OPENROUTER_API_KEY':'or','GROQ_API_KEY':'groq'}), \
         patch.object(lg,'_request_groq',side_effect=RuntimeError('Groq unavailable')) as groq, \
         patch.object(lg,'_request_openrouter',return_value='Router fallback line.') as router:
        assert lg._request_fallback({'x':'masked'},2)=='Router fallback line.'
        groq.assert_called_once()
        router.assert_called_once()

def test_request_malformed_json_fails_open(monkeypatch):
    monkeypatch.setattr(lg,'_config',lambda:(True,'key','model','v1',5,.1))
    monkeypatch.setattr(lg,'get_connection_pool',lambda: (_ for _ in ()).throw(RuntimeError('db offline')))
    result=lg.resolve_bot_line(scenario_id=1,session_id='s',target_node=2,intent='unknown',user_text_masked='safe phrase',fixed_text='Fixed reply.',is_reprompt=True)
    assert result.text=='Fixed reply.' and result.source=='fixed'

def test_masked_input_only_in_prompt_context():
    context={'player_text':'my phone ****','recent_turns':[{'player_text_masked':'mail [email]'}]}
    serialized=lg.build_prompt_payload(context)
    assert '123456789' not in serialized and 'private@example.com' not in serialized
    assert json.loads(serialized)==context


def test_cached_line_is_rechecked_against_current_requested_action():
    from contextlib import contextmanager
    bad={'line_text':'Anh chị xuống sảnh nhận hàng giúp tôi nhé.','line_id':1,'use_count':0}
    class Pool:
        @contextmanager
        def connection(self):yield self
        @contextmanager
        def cursor(self):yield self
        def execute(self,sql,params=()):self.query=sql
        def fetchone(self):
            if ' AS payload' in self.query:return {'payload':{'family':'delivery','scenario_kind':'fraud'}}
            if 'SELECT node_key' in self.query:return {'requested_action':'share_sensitive'}
            if 'FROM dialogue_lines' in self.query:return bad
            return None
        def fetchall(self):
            if 'FROM call_turns' in self.query:return []
            if 'FROM dialogue_lines' in self.query:return [bad]
            return []
    fixed='Anh chị đọc mã đăng nhập trong tin nhắn để tôi xác nhận nhé.'
    with patch.object(lg,'get_connection_pool',return_value=Pool()), \
         patch.object(lg,'_config',return_value=(True,True,'test','test',1,1)), \
         patch.object(lg,'memory_context',return_value={}), \
         patch.object(lg,'_request_line',side_effect=RuntimeError('unavailable')):
        result=lg.resolve_bot_line(scenario_id=1,session_id='s',target_node=2,intent='comply',user_text_masked='Tôi đang nghe',fixed_text=fixed,is_reprompt=False,context={'conversation_ending':False})
    assert result.source=='fixed' and result.text==fixed


def test_cache_context_keeps_facts_history_and_mode_separate():
    base={'player_text':'Một câu nói','interaction_mode':'call','recent_turns':[],'case_facts':{'place':'sảnh'}}
    assert lg.context_cache_key(base)==lg.context_cache_key({**base,'player_text':'Câu gần nghĩa','_generated_model':'test'})
    for change in [{'case_facts':{'place':'quầy'}},{'interaction_mode':'message'},
                   {'recent_turns':[{'player_text_masked':'Tôi đã từ chối'}]}, {'conversation_summary':'Bối cảnh khác'}]:
        assert lg.context_cache_key(base)!=lg.context_cache_key({**base,**change})
