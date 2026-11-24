"""Optional, fail-open LLM dialogue line generation and PostgreSQL cache."""
from __future__ import annotations

import json, logging, os, re, time
from dataclasses import dataclass
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from app.arena.normalization import normalize_phrase
from app.arena.phone_dialogue import phone_opening, listening_acknowledgement
from app.database import get_connection_pool
from app.arena.conversation_memory import memory_context
from app.arena.xapikey_client import request_json as request_xapikey_json, settings as xapikey_settings

log = logging.getLogger(__name__)
from app.arena.prompts import DIALOGUE_PROMPT

INTENTS = ('verify','refuse','doubt','comply','share_sensitive','transfer_money','hang_up','unknown')

@dataclass
class LineResult:
    text: str
    line_id: int | None
    source: str
    latency_ms: int

def _config():
    provider_configured=any(os.getenv(name,'').strip() for name in ('GEMINI_API_KEY','GROQ_API_KEY','OPENROUTER_API_KEY','XAPIKEY_CALL_API_KEY','XAPIKEY_MESSAGE_API_KEY'))
    return (os.getenv('LINE_LLM_ENABLED','false').lower() in {'true','1'}, provider_configured,
            os.getenv('GEMINI_MODEL','gemini-2.5-flash').strip(), os.getenv('LINE_PROMPT_VERSION','v3'),
            max(1,int(os.getenv('LINE_POOL_SIZE','5'))), max(.1,float(os.getenv('LINE_LLM_TIMEOUT_SECONDS','3'))))

def cache_key(masked: str, original: str | None = None) -> str | None:
    if len(masked) > 200 or (original is not None and masked != original): return None
    return normalize_phrase(masked) or None

def validate_line(text, player_text='', context=None):
    if not isinstance(text,str): return None
    text=text.strip()
    if not 5 <= len(text) <= 300 or not re.sub(r'\s+',' ',text).strip(): return None
    if re.search(r'https?://|www\.|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\d{4,}',text,re.I): return None
    if re.search(r'\b(?:tôi là (?:một )?ai|mô hình ngôn ngữ|trợ lý ai|as an ai)\b',text,re.I): return None
    if '```' in text or text.strip().casefold()==player_text.strip().casefold(): return None
    if context:
        if context.get('phone_ui'):
            from app.arena.phone_ui import unsupported_screen_request
            if unsupported_screen_request(text): return None
        if context.get('conversation_ending') is False:
            closing = normalize_phrase(text)
            if re.search(r'\b(?:(?:ket thuc|ngat|cup|dung) (?:cuoc goi|may)|tam biet|hen gap lai)\b',closing):
                return None
            if re.search(r'\b(?:da|se) (?:ghi nhan|xac nhan|dat lich)\b.*\b(?:xin cho|lien he lai|cam on)\b',closing):
                return None
        if 'biên lai' in text.casefold() and not any(m.get('channel')=='receipt' for m in context.get('available_messages',[])):
            return None
        if listening_acknowledgement(player_text) and re.search(
                r"con nghe may|giai thich.*yeu cau cua (?:minh|ban)", normalize_phrase(text)):
            return None
        line_fold=text.casefold()
        scenario_context=' '.join(str(context.get(k,'')) for k in (
            'scenario_title','scenario_category','sample_line','user_context','objective','requested_action','tactics'))
        persona=context.get('persona',{})
        if isinstance(persona,dict): scenario_context+=' '+' '.join(str(v) for v in persona.values())
        for turn in context.get('recent_turns',[]):
            if isinstance(turn,dict): scenario_context+=' '+' '.join(str(turn.get(k,'')) for k in ('player_text_masked','bot_line'))
        support=scenario_context.casefold()
        bank_terms=('ngân hàng','tài khoản','otp','mã xác thực','mã bảo mật','sms','giao dịch bất thường')
        prize_terms=('trúng thưởng','giải thưởng','nhận thưởng','phí thủ tục','chương trình tri ân')
        if any(term in line_fold for term in bank_terms) and not any(term in support for term in bank_terms): return None
        if any(term in line_fold for term in prize_terms) and not any(term in support for term in prize_terms): return None
    return re.sub(r'\s+',' ',text).strip()

def build_prompt_payload(context):
    return json.dumps({key:value for key,value in context.items() if not key.startswith('_')},ensure_ascii=False)

def _request_line(context, model, timeout):
    context.pop('_generated_model',None)
    key=os.getenv('GEMINI_API_KEY','').strip()
    if not key:
        if _fallback_configured(context):
            return _request_fallback(context,timeout)
        raise RuntimeError('not_configured')
    instructions = DIALOGUE_PROMPT
    payload={'systemInstruction':{'parts':[{'text':instructions}]},
      'contents':[{'role':'user','parts':[{'text':build_prompt_payload(context)}]}],
      'generationConfig':{'responseMimeType':'application/json','responseSchema':{'type':'OBJECT','properties':{'line':{'type':'STRING'}},'required':['line']},'maxOutputTokens':256}}
    if model.startswith('gemini-2.5-flash'):
        payload['generationConfig']['thinkingConfig']={'thinkingBudget':0}
    endpoint=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    req=Request(endpoint,data=json.dumps(payload).encode(),headers={'x-goog-api-key':key,'Content-Type':'application/json'},method='POST')
    try:
        with urlopen(req,timeout=timeout) as r: body=json.loads(r.read().decode())
    except HTTPError as exc:
        # Do not include request headers or API credentials in diagnostics.
        detail=f'Gemini HTTP {exc.code}: {exc.read().decode("utf-8",errors="replace")[:300]}'
        if _fallback_configured(context):
            log.warning('%s; trying configured fallback providers',detail)
            return _request_fallback(context,timeout)
        raise RuntimeError(detail) from exc
    except Exception as exc:
        if _fallback_configured(context):
            log.warning('Gemini request failed (%s); trying configured fallback providers',type(exc).__name__)
            return _request_fallback(context,timeout)
        raise
    candidates=body.get('candidates',[])
    first_candidate=candidates[0] if candidates else {}
    out=''.join(p['text'] for p in first_candidate.get('content',{}).get('parts',[])
                if isinstance(p.get('text'),str) and not p.get('thought'))
    if not out:
        reason=candidates[0].get('finishReason','no_text') if candidates else body.get('promptFeedback',{}).get('blockReason','no_candidate')
        if _fallback_configured(context):
            log.warning('Gemini returned no text; trying configured fallback providers')
            return _request_fallback(context,timeout)
        raise ValueError(f'Gemini returned no text (finishReason={reason})')
    try:
        parsed=json.loads(out)
    except json.JSONDecodeError as exc:
        # Some Gemini responses prepend a short preamble despite JSON mode.
        # Decode the first complete JSON object, but never accept plain prose.
        parsed=None
        decoder=json.JSONDecoder()
        for index,char in enumerate(out):
            if char=='{':
                try:
                    parsed,_=decoder.raw_decode(out[index:])
                    break
                except json.JSONDecodeError:
                    continue
        if parsed is None:
            if _fallback_configured(context):
                log.warning('Gemini returned invalid JSON; trying configured fallback providers')
                return _request_fallback(context,timeout)
            raise ValueError(f'Gemini returned invalid JSON: {out[:180]!r}') from exc
    if not isinstance(parsed,dict) or not isinstance(parsed.get('line'),str):
        if _fallback_configured(context):
            log.warning('Gemini JSON did not contain a line; trying configured fallback providers')
            return _request_fallback(context,timeout)
        raise ValueError('Gemini JSON did not contain a string line')
    context['_generated_model']=model
    return parsed['line']

def _fallback_configured(context):
    return bool(
        os.getenv('GROQ_API_KEY', '').strip()
        or os.getenv('OPENROUTER_API_KEY', '').strip()
        or xapikey_settings(context.get('interaction_mode', 'message'))[0]
    )


def _request_fallback(context, timeout):
    providers = []
    if os.getenv('GROQ_API_KEY', '').strip():
        providers.append(("Groq", _request_groq))
    if os.getenv('OPENROUTER_API_KEY', '').strip():
        providers.append(("OpenRouter", _request_openrouter))
    if xapikey_settings(context.get('interaction_mode', 'message'))[0]:
        providers.append(("X-APIKEY", _request_xapikey))
    for index, (provider, request_line) in enumerate(providers):
        try:
            line = request_line(context, timeout)
            if not validate_line(line, context.get('player_text', ''), context):
                raise ValueError('Invalid generated line')
            if provider != "X-APIKEY":
                variable = "GROQ_MODEL" if provider == "Groq" else "OPENROUTER_MODEL"
                default = "openai/gpt-oss-20b" if provider == "Groq" else "openrouter/free"
                context["_generated_model"] = os.getenv(variable, default)
            return line
        except Exception as exc:
            if index == len(providers) - 1:
                raise
            log.warning('%s fallback failed (%s); trying next provider', provider, type(exc).__name__)
    raise RuntimeError('No fallback provider configured')


def _request_xapikey(context, timeout):
    instructions = DIALOGUE_PROMPT
    clean_context = {key: value for key, value in context.items() if not key.startswith("_")}
    parsed, model = request_xapikey_json(instructions, clean_context, max_tokens=400)
    if not isinstance(parsed.get('line'), str):
        raise ValueError('X-APIKEY JSON did not contain a string line')
    context["_generated_model"] = model
    return parsed['line']


def _request_openrouter(context,timeout):
    key=os.getenv('OPENROUTER_API_KEY','').strip()
    if not key: raise RuntimeError('OpenRouter fallback not configured')
    model=os.getenv('OPENROUTER_MODEL','openrouter/free').strip()
    instructions = DIALOGUE_PROMPT
    payload={'model':model,'messages':[{'role':'system','content':instructions},{'role':'user','content':build_prompt_payload(context)}],
      'max_tokens':800}
    req=Request('https://openrouter.ai/api/v1/chat/completions',data=json.dumps(payload).encode(),
      headers={'Authorization':f'Bearer {key}','Content-Type':'application/json','HTTP-Referer':'https://scam-arena.local','X-Title':'Scam Arena'},method='POST')
    try:
        with urlopen(req,timeout=timeout) as response: body=json.loads(response.read().decode())
    except HTTPError as exc:
        raise RuntimeError(f'OpenRouter HTTP {exc.code}: {exc.read().decode("utf-8",errors="replace")[:300]}') from exc
    message=body.get('choices',[{}])[0].get('message',{})
    out=message.get('content')
    if isinstance(out,list):
        out=''.join(part.get('text','') for part in out if isinstance(part,dict))
    if not isinstance(out,str) or not out.strip():
        reason=message.get('refusal') or body.get('choices',[{}])[0].get('finish_reason') or 'empty_content'
        raise ValueError(f'OpenRouter returned no text content (reason={str(reason)[:100]})')
    try:
        parsed=json.loads(out)
    except json.JSONDecodeError as exc:
        decoder=json.JSONDecoder(); parsed=None
        for index,char in enumerate(out):
            if char=='{':
                try:
                    parsed,_=decoder.raw_decode(out[index:]); break
                except json.JSONDecodeError:
                    continue
        if parsed is None: raise ValueError(f'OpenRouter returned invalid JSON: {out[:160]!r}') from exc
    if not isinstance(parsed,dict) or not isinstance(parsed.get('line'),str): raise ValueError('OpenRouter JSON did not contain a string line')
    return parsed['line']

def _request_groq(context,timeout):
    key=os.getenv('GROQ_API_KEY','').strip()
    if not key: raise RuntimeError('Groq fallback not configured')
    model=os.getenv('GROQ_MODEL','openai/gpt-oss-20b').strip()
    instructions = DIALOGUE_PROMPT
    payload={'model':model,'messages':[{'role':'system','content':instructions},{'role':'user','content':build_prompt_payload(context)}],
      'max_completion_tokens':500,'temperature':0.7}
    if model.startswith('openai/gpt-oss-'):
        payload.update(reasoning_effort='low',reasoning_format='hidden',response_format={'type':'json_object'})
    req=Request('https://api.groq.com/openai/v1/chat/completions',data=json.dumps(payload).encode(),
      headers={'Authorization':f'Bearer {key}','Content-Type':'application/json','User-Agent':'ScamArena/1.0'},method='POST')
    try:
        with urlopen(req,timeout=timeout) as response: body=json.loads(response.read().decode())
    except HTTPError as exc:
        raise RuntimeError(f'Groq HTTP {exc.code}: {exc.read().decode("utf-8",errors="replace")[:300]}') from exc
    out=body.get('choices',[{}])[0].get('message',{}).get('content')
    if not isinstance(out,str) or not out.strip(): raise ValueError('Groq returned no text content')
    try: parsed=json.loads(out)
    except json.JSONDecodeError as exc:
        decoder=json.JSONDecoder(); parsed=None
        for index,char in enumerate(out):
            if char=='{':
                try: parsed,_=decoder.raw_decode(out[index:]); break
                except json.JSONDecodeError: continue
        if parsed is None: raise ValueError(f'Groq returned invalid JSON: {out[:160]!r}') from exc
    if not isinstance(parsed,dict) or not isinstance(parsed.get('line'),str): raise ValueError('Groq JSON did not contain a string line')
    return parsed['line']

def pick_from_pool(rows, previous=None):
    choices=[r for r in rows if r['line_text'] != previous] or rows
    preferred=[r for r in choices if r.get('preference_score',0) >= 0]
    if preferred: choices=preferred
    return min(choices,key=lambda r:(-r.get('preference_score',0),r['use_count'],r['line_id'])) if choices else None

def resolve_bot_line(*,scenario_id,session_id,target_node,intent,user_text_masked,fixed_text,is_reprompt,terminal=False,original_user_text=None,context=None):
    enabled,key,model,version,pool_size,timeout=_config(); start=time.monotonic()
    fixed=LineResult(fixed_text,None,'fixed',0)
    if not enabled or not key or terminal:return fixed
    norm=cache_key(user_text_masked,original_user_text)
    try:
        with get_connection_pool().connection() as c, c.cursor() as cur:
            # Supply only published scenario metadata, the chosen target node and masked history.
            cur.execute("""SELECT v.definition->'payload' || jsonb_build_object('title',v.definition->>'title') AS payload
                           FROM call_sessions cs JOIN scenario_versions v ON v.version_id=cs.scenario_version_id
                           WHERE cs.session_id=%s""",(session_id,)); scenario_row=cur.fetchone()
            cur.execute("SELECT node_key,objective,tactic,requested_action FROM dialogue_nodes WHERE node_id=%s",(target_node,)); node_row=cur.fetchone()
            cur.execute("SELECT turn_no,user_text_masked,intent,bot_reply_text FROM call_turns WHERE session_id=%s ORDER BY turn_no DESC LIMIT 4",(session_id,)); history=list(reversed(cur.fetchall()))
            payload=scenario_row['payload'] if scenario_row else {}
            persona=payload.get('persona',{}) if isinstance(payload,dict) else {}
            if context is None: context={}
            context.update({'scenario_title':payload.get('title','') if isinstance(payload,dict) else '',
                'scenario_kind':payload.get('scenario_kind','fraud'),
                'scenario_category':payload.get('category','') if isinstance(payload,dict) else '',
                'persona':persona,'user_context':payload.get('user_context','') if isinstance(payload,dict) else '',
                'objective':(node_row or {}).get('objective',''),'tactics':[(node_row or {}).get('tactic','')],
                'requested_action':(node_row or {}).get('requested_action','other'),'sample_line':fixed_text,
                'intent':intent,'player_text':user_text_masked,
                'recent_turns':[{'player_text_masked':r['user_text_masked'],'intent':r['intent'],'bot_line':r['bot_reply_text']} for r in history]})
            context.update(memory_context(cur,session_id,before_turn=(history[-1].get('turn_no',0)+1 if history else 1),
                recent_start=(history[0].get('turn_no',0) if history else 0)))
            has_memory=bool(context.get('conversation_summary') or context.get('earlier_unsummarized_turns') or context.get('available_messages'))
            params=(scenario_id,target_node,intent,is_reprompt,version)
            # An unclear reply can mean different things in different conversations.
            # Give the LLM the current context before falling back to stored lines.
            if not has_memory:
                if norm and intent != 'unknown' and not has_memory:
                    cur.execute("SELECT * FROM dialogue_lines WHERE node_id=%s AND intent=%s AND is_reprompt=%s AND prompt_version=%s AND player_text_norm=%s AND source='llm' AND enabled AND preference_score >= 0 ORDER BY preference_score DESC,use_count,line_id LIMIT 1",params[1:]+(norm,)); row=cur.fetchone()
                    if row: return _use(cur,row,'cache_exact',start)
                cur.execute("SELECT * FROM dialogue_lines WHERE node_id=%s AND intent=%s AND is_reprompt=%s AND prompt_version=%s AND source='llm' AND enabled ORDER BY preference_score DESC,use_count,line_id",params[1:]); rows=cur.fetchall()
                prev=None
                cur.execute("SELECT bot_reply_text FROM call_turns WHERE session_id=%s ORDER BY turn_no DESC LIMIT 1",(session_id,)); p=cur.fetchone(); prev=p['bot_reply_text'] if p else None
                chosen=pick_from_pool(rows,prev)
                if intent != 'unknown' and not has_memory and len(rows)>=pool_size and chosen:return _use(cur,chosen,'cache_pool',start)
        line=validate_line(_request_line(context or {'sample_line':fixed_text,'intent':intent,'player_text':user_text_masked},model,timeout),user_text_masked,context)
        if not line: raise ValueError('invalid line')
        if has_memory:
            return LineResult(line,None,'llm',int((time.monotonic()-start)*1000))
        with get_connection_pool().connection() as c, c.cursor() as cur:
            cur.execute("INSERT INTO dialogue_lines(node_id,intent,is_reprompt,player_text_norm,line_text,source,model,prompt_version) VALUES(%s,%s,%s,%s,%s,'llm',%s,%s) ON CONFLICT DO NOTHING RETURNING line_id",(target_node,intent,is_reprompt,norm,line,context.get('_generated_model',model),version)); got=cur.fetchone()
            if got:return LineResult(line,got['line_id'],'llm',int((time.monotonic()-start)*1000))
            cur.execute("SELECT * FROM dialogue_lines WHERE node_id=%s AND intent=%s AND is_reprompt=%s AND prompt_version=%s AND source='llm' AND enabled ORDER BY preference_score DESC,use_count,line_id",(target_node,intent,is_reprompt,version)); rows=cur.fetchall()
            chosen=pick_from_pool(rows)
            if chosen and not has_memory:return _use(cur,chosen,'cache_pool',start)
        return fixed
    except Exception as exc:
        log.warning('Generated line unavailable: %s',exc)
        if intent == 'unknown' or (context and (context.get('conversation_summary') or context.get('earlier_unsummarized_turns') or context.get('available_messages'))): return fixed
        try:
            with get_connection_pool().connection() as c,c.cursor() as cur:
                cur.execute("SELECT * FROM dialogue_lines WHERE node_id=%s AND intent=%s AND is_reprompt=%s AND prompt_version=%s AND source='llm' AND enabled ORDER BY preference_score DESC,use_count,line_id",(target_node,intent,is_reprompt,version)); rows=cur.fetchall()
                cur.execute("SELECT bot_reply_text FROM call_turns WHERE session_id=%s ORDER BY turn_no DESC LIMIT 1",(session_id,)); prev=cur.fetchone()
                chosen=pick_from_pool(rows,prev['bot_reply_text'] if prev else None)
                if chosen:return _use(cur,chosen,'cache_pool',start)
        except Exception as cache_exc: log.warning('Line cache unavailable: %s',cache_exc)
        return fixed

def _use(cur,row,source,start):
    cur.execute('UPDATE dialogue_lines SET use_count=use_count+1 WHERE line_id=%s',(row['line_id'],))
    return LineResult(row['line_text'],row['line_id'],source,int((time.monotonic()-start)*1000))


def regenerate_line_for_turn(*,session_id,turn_no,old_line_id=None,user_id):
    """Generate a fresh alternative for an existing turn without changing game state."""
    enabled,key,model,version,_,timeout=_config()
    if not enabled or not key:
        raise RuntimeError('LLM chưa được bật hoặc chưa cấu hình API key Gemini, Groq, OpenRouter hay X-APIKEY.')
    start=time.monotonic()
    with get_connection_pool().connection() as c,c.cursor() as cur:
        cur.execute("""SELECT sc.scenario_id,sc.scenario_name,v.definition->>'title' AS title,v.definition->'payload' AS payload,t.target_node_id,t.intent,t.is_reprompt,
                            t.user_text_masked,t.bot_reply_text,t.line_id,default_line.line_text AS text,n.node_key,
                            n.objective,n.tactic,n.requested_action,s.interaction_mode,s.case_parameters,opening.line_text AS opening_text
                     FROM call_turns t JOIN call_sessions s USING(session_id)
                     JOIN scenarios sc ON sc.scenario_id=s.scenario_id
                     JOIN scenario_versions v ON v.version_id=s.scenario_version_id
                     LEFT JOIN dialogue_lines opening ON opening.line_id=s.opening_line_id
                     LEFT JOIN dialogue_nodes n ON n.node_id=t.target_node_id
                     LEFT JOIN dialogue_lines default_line ON default_line.node_id=n.node_id
                       AND default_line.source='fixed' AND default_line.is_reprompt=t.is_reprompt
                     WHERE t.session_id=%s AND s.user_id=%s AND t.turn_no=%s""",(session_id,user_id,turn_no))
        row=cur.fetchone()
        if not row: raise LookupError('Không tìm thấy lượt cần tạo lại lời thoại.')
        if not row['target_node_id'] or not row['intent']:
            raise RuntimeError('Lượt này chưa có đủ dữ liệu đích để tạo lại lời thoại.')
        cur.execute("SELECT is_terminal FROM dialogue_nodes WHERE node_id=%s",(row['target_node_id'],))
        terminal=cur.fetchone()
        if not terminal or terminal['is_terminal']:
            raise RuntimeError('Không thể tạo lời thoại cho node kết thúc.')
        cur.execute("""SELECT turn_no,user_text_masked,intent,bot_reply_text FROM call_turns
                       WHERE session_id=%s AND turn_no<%s ORDER BY turn_no DESC LIMIT 4""",(session_id,turn_no))
        history=list(reversed(cur.fetchall()))
        scenario=row['payload'] if isinstance(row['payload'],dict) else {}
        from app.arena.notifications import brief
        available_messages=brief(cur,session_id)
        from app.arena.practice_catalog import render
        context={'interaction_mode':row['interaction_mode'],'scenario_title':row['title'] or scenario.get('title',row['scenario_name']),
            'scenario_kind':scenario.get('scenario_kind','fraud'),
            'scenario_category':scenario.get('category',''),'persona':scenario.get('persona',{}),
            'user_context':scenario.get('user_context',''),'objective':row['objective'] or '',
            'tactics':[row['tactic']] if row['tactic'] else [],'requested_action':row['requested_action'] or 'other',
            'sample_line':render(row['text'] or row['bot_reply_text'] or '',row['case_parameters']), 'intent':row['intent'],
            'case_facts':row['case_parameters'],
            'available_messages':available_messages, 'conversation_ending':False, 'phone_ui':row['interaction_mode']=='call',
            'player_text':row['user_text_masked'] or '',
            'caller_line':history[-1]['bot_reply_text'] if history else (
                phone_opening(row.get('opening_text') or '') if row['interaction_mode']=='call' else row.get('opening_text') or ''),
            'recent_turns':[{'player_text_masked':r['user_text_masked'],'intent':r['intent'],'bot_line':r['bot_reply_text']} for r in history],
            'avoid_lines':[row['bot_reply_text']] if row['bot_reply_text'] else [],
            'instruction':'Đây là lần trả lời lại cùng một câu người chơi. Hãy đưa ra phản ứng khác, tự nhiên và đúng tình huống; không lặp câu cũ.'}
        context.update(memory_context(cur,session_id,before_turn=turn_no,recent_start=(history[0].get('turn_no',0) if history else 0)))
        if old_line_id is not None:
            cur.execute("SELECT line_text FROM dialogue_lines WHERE line_id=%s AND node_id=%s AND source='llm'",(old_line_id,row['target_node_id']))
            prior=cur.fetchone()
            if prior and prior['line_text'] not in context['avoid_lines']:
                context['avoid_lines'].append(prior['line_text'])
        scenario_id=row['scenario_id']; node_id=row['target_node_id']; intent=row['intent']
        is_reprompt=row['is_reprompt']
    for _ in range(2):
        line=validate_line(_request_line(context,model,timeout),context['player_text'],context)
        if not line: continue
        if row['bot_reply_text'] and line.casefold()==row['bot_reply_text'].strip().casefold():
            context.setdefault('avoid_lines',[]).append(line)
            continue
        if context.get('conversation_summary') or context.get('earlier_unsummarized_turns') or context.get('available_messages'):
            return LineResult(line,None,'llm',int((time.monotonic()-start)*1000))
        with get_connection_pool().connection() as c,c.cursor() as cur:
            cur.execute("""INSERT INTO dialogue_lines(node_id,intent,is_reprompt,player_text_norm,
                         line_text,source,model,prompt_version) VALUES(%s,%s,%s,NULL,%s,'llm',%s,%s)
                         ON CONFLICT DO NOTHING RETURNING line_id""",
                        (node_id,intent,is_reprompt,line,context.get('_generated_model',model),version))
            inserted=cur.fetchone()
            if inserted:
                return LineResult(line,inserted['line_id'],'llm',int((time.monotonic()-start)*1000))
            cur.execute("""SELECT line_id,line_text FROM dialogue_lines WHERE node_id=%s
                         AND intent=%s AND is_reprompt=%s AND source='llm' AND md5(line_text)=md5(%s) AND line_text<>%s
                         AND (%s::bigint IS NULL OR line_id<>%s) AND enabled
                         ORDER BY preference_score DESC,line_id LIMIT 1""",
                        (node_id,intent,is_reprompt,line,row['bot_reply_text'] or '',old_line_id,old_line_id))
            existing=cur.fetchone()
            if existing:
                return _use(cur,existing,'cache_pool',start)
        context.setdefault('avoid_lines',[]).append(line)
    raise RuntimeError('LLM không tạo được câu trả lời mới khác câu cũ.')
