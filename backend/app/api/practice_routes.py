"""Owned simulated evidence, independent evaluation and admin-only publication."""
import json
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb
from app.auth import get_current_user, require_admin
from app.database import get_connection_pool
from app.arena.practice_catalog import FAMILIES, render,case_spec
from app.arena.scenario_loader import _load_one
from app.arena.scenario_versions import publish_document,validated_document
from app.arena.conversation_memory import mask

router=APIRouter(prefix='/api/practice',tags=['practice'])

class Judgement(BaseModel):
    judgement: Literal['benign','fraud','uncertain']
    reason: str = Field(default='',max_length=1000)

class Event(BaseModel):
    event_type: Literal['check_context','read_message','verify_official','open_requested_link','share_demo_code']

class Review(BaseModel):
    document: dict


class Selection(BaseModel):
    enabled: bool
    weight: float = Field(gt=0,le=10000,allow_inf_nan=False)


def owned(cursor,session_id,user_id,lock=False):
    cursor.execute("""SELECT cs.ended_at,cs.outcome,cs.case_parameters,cs.exercise_mode,n.requested_action,
                             cs.world_state,v.definition FROM call_sessions cs
                       JOIN scenario_versions v ON v.version_id=cs.scenario_version_id
                       JOIN dialogue_nodes n ON n.node_id=cs.current_node_id
                       WHERE cs.session_id=%s AND cs.user_id=%s"""+(' FOR UPDATE OF cs' if lock else ''),(session_id,user_id))
    row=cursor.fetchone()
    if not row or row['definition'].get('family') not in FAMILIES:
        raise HTTPException(404,'Không tìm thấy phiên luyện tập.')
    return row


@router.get('/{session_id}/context')
def context(session_id: UUID,user=Depends(get_current_user)):
    with get_connection_pool().connection() as c,c.cursor() as cur:
        row=owned(cur,session_id,user['user_id'])
    family=row['definition']['family'];spec=case_spec(row['definition'])
    actions=['check_context','read_message','verify_official']
    if row['requested_action'] in ['install_app','click_link']: actions.append('open_requested_link')
    if row['requested_action']=='share_sensitive': actions.append('share_demo_code')
    return {'context':render(spec['context'],row['case_parameters']),'actions':actions,'ended':bool(row['ended_at'])}


@router.post('/{session_id}/events')
def record_event(session_id: UUID,body: Event,user=Depends(get_current_user)):
    with get_connection_pool().connection() as c,c.cursor() as cur:
        row=owned(cur,session_id,user['user_id'],True)
        if row['ended_at']: raise HTTPException(409,'Cuộc gọi đã kết thúc.')
        action=body.event_type
        if action=='open_requested_link' and row['requested_action'] not in ['install_app','click_link']:
            raise HTTPException(409,'Chưa có yêu cầu mở liên kết trong cuộc gọi.')
        if action=='share_demo_code' and row['requested_action']!='share_sensitive':
            raise HTTPException(409,'Chưa có yêu cầu đọc mã trong cuộc gọi.')
        if action!='read_message':
            cur.execute('INSERT INTO practice_events(session_id,event_type) VALUES(%s,%s) ON CONFLICT DO NOTHING',(session_id,action))
        spec=case_spec(row['definition'])
        text=spec['evidence'] if action=='check_context' else spec['official'] if action=='verify_official' else (
            'Mở hộp thư trong điện thoại để xem SMS và email đã nhận.' if action=='read_message' else
            'Bạn đã chọn thực hiện thao tác mô phỏng. Không có liên kết ngoài được mở và không có dữ liệu thật được gửi.')
        return {'event_type':action,'text':render(text,row['case_parameters'])}


@router.post('/{session_id}/check-order')
def check_order(session_id: UUID,user=Depends(get_current_user)):
    result=record_event(session_id,Event(event_type='check_context'),user)
    return {'order':result['text'],'delivery':'Đây là dữ liệu mô phỏng, không phải đơn hàng thật.'}


@router.post('/{session_id}/judge')
def judge(session_id: UUID,body: Judgement,user=Depends(get_current_user)):
    with get_connection_pool().connection() as c,c.cursor() as cur:
        row=owned(cur,session_id,user['user_id'],True)
        if not row['ended_at']: raise HTTPException(409,'Hãy kết thúc cuộc gọi trước khi xem đánh giá.')
        cur.execute('INSERT INTO practice_judgements(session_id,judgement,reason) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(session_id,body.judgement,mask(body.reason)))
        cur.execute('SELECT judgement,reason,evaluation FROM practice_judgements WHERE session_id=%s',(session_id,));saved=cur.fetchone();choice=saved['judgement']
        if saved['evaluation']: return saved['evaluation']
        cur.execute('SELECT event_type FROM practice_events WHERE session_id=%s',(session_id,));events={r['event_type'] for r in cur.fetchall()}
        risk=bool(events & {'open_requested_link','share_demo_code'})
        verified='verify_official' in events
        checked=bool(events & {'check_order','check_context'})
        correct=choice==row['definition']['scenario_kind']
        # Spoken compliance is a signal, not proof an external action occurred.
        score=(40 if correct else 20 if choice=='uncertain' else 0)+(30 if verified else 15 if checked else 0)+(0 if risk else 30)
        result={'judgement':choice,'reason':saved['reason'],'actual_kind':row['definition']['scenario_kind'],
                'correct':correct,'checked_order':checked,'verified_independently':verified,
                'risk_action_recorded':risk,'risk_signal_in_dialogue':row['outcome']=='scammed',
                'evaluation_score':score,'rubric_version':'practice-v1',
                'explanation':row['definition']['payload']['lesson_summary'],
                'note':'Chưa đủ thông tin được tách khỏi kết luận sai. Dừng cuộc gọi không tự nó chứng minh thật/giả. Điểm không phụ thuộc tốc độ trả lời.'}
        cur.execute('UPDATE practice_judgements SET evaluation=%s WHERE session_id=%s AND evaluation IS NULL',(Jsonb(result),session_id))
        return result


@router.get('/admin/report')
def report(user=Depends(require_admin)):
    with get_connection_pool().connection() as c:
        rows=c.execute("""SELECT v.definition->>'family' AS family,v.definition->>'scenario_kind' AS actual,
                                 j.judgement,count(*) AS count
                          FROM practice_judgements j JOIN call_sessions cs USING(session_id)
                          JOIN scenario_versions v ON v.version_id=cs.scenario_version_id
                          GROUP BY 1,2,3 ORDER BY 1,2,3""").fetchall()
        events=c.execute('SELECT event_type,count(*) AS count FROM practice_events GROUP BY event_type ORDER BY event_type').fetchall()
    total=sum(r['count'] for r in rows)
    correct=sum(r['count'] for r in rows if r['actual']==r['judgement'])
    benign=sum(r['count'] for r in rows if r['actual']=='benign')
    fraud=sum(r['count'] for r in rows if r['actual']=='fraud')
    return {'classification':rows,'events':events,'total':total,'correct':correct,
            'accuracy':correct/total if total else None,'benign_total':benign,'fraud_total':fraud,
            'false_alarms':sum(r['count'] for r in rows if r['actual']=='benign' and r['judgement']=='fraud'),
            'missed_frauds':sum(r['count'] for r in rows if r['actual']=='fraud' and r['judgement']=='benign'),
            'uncertain':sum(r['count'] for r in rows if r['judgement']=='uncertain')}


@router.get('/admin/reviews')
def reviews(user=Depends(require_admin)):
    with get_connection_pool().connection() as c:
        return c.execute('SELECT review_id,document,status,created_at,published_version_id FROM practice_reviews ORDER BY review_id DESC LIMIT 100').fetchall()


@router.get('/admin/catalog')
def catalog(user=Depends(require_admin)):
    with get_connection_pool().connection() as c:
        return c.execute("""SELECT s.scenario_id,s.scenario_name,s.status,s.selection_weight,v.revision,
                                  v.definition->'document' AS document FROM scenarios s
                           JOIN scenario_versions v ON v.version_id=s.active_version_id
                           WHERE s.scenario_name LIKE 'practice-%' ORDER BY s.scenario_id""").fetchall()


@router.post('/admin/catalog/{scenario_id}/selection')
def configure_selection(scenario_id: int,body: Selection,user=Depends(require_admin)):
    with get_connection_pool().connection() as c:
        row=c.execute("""UPDATE scenarios SET status=%s,selection_weight=%s
                         WHERE scenario_id=%s AND scenario_name LIKE 'practice-%%' RETURNING scenario_id,status,selection_weight""",
                      ('published' if body.enabled else 'archived',body.weight,scenario_id)).fetchone()
        if not row: raise HTTPException(404,'Không tìm thấy tình huống.')
        return row


def checked_document(document):
    if len(json.dumps(document))>200000: raise HTTPException(413,'Kịch bản quá lớn.')
    try:
        doc=validated_document(document)
        if doc['family'] not in FAMILIES: raise ValueError('Họ tình huống chưa được hỗ trợ.')
        if not doc['id'].startswith('practice-'): raise ValueError('ID tình huống phải bắt đầu bằng practice-.')
        if doc['status']!='published': raise ValueError('Bản đề xuất phải có status=published; chỉ phát hành sau khi admin bấm duyệt.')
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    return doc


class Draft(BaseModel):
    document: dict
    draft_id: int | None = Field(default=None,gt=0)
    expected_revision: int | None = Field(default=None,gt=0)


@router.post('/admin/validate')
def validate_preview(body: Review,user=Depends(require_admin)):
    return {'document':checked_document(body.document),'valid':True}


@router.get('/admin/drafts')
def drafts(user=Depends(require_admin)):
    with get_connection_pool().connection() as c:
        return c.execute('SELECT draft_id,document,revision,updated_at FROM practice_admin_drafts WHERE owner_id=%s ORDER BY updated_at DESC LIMIT 100',(user['user_id'],)).fetchall()


@router.post('/admin/drafts')
def save_draft(body: Draft,user=Depends(require_admin)):
    if len(json.dumps(body.document))>200000: raise HTTPException(413,'Bản nháp quá lớn.')
    with get_connection_pool().connection() as c:
        if body.draft_id is None:
            return c.execute('INSERT INTO practice_admin_drafts(owner_id,document) VALUES(%s,%s) RETURNING draft_id,revision,updated_at',(user['user_id'],Jsonb(body.document))).fetchone()
        row=c.execute('UPDATE practice_admin_drafts SET document=%s,revision=revision+1,updated_at=now() WHERE draft_id=%s AND owner_id=%s AND revision=%s RETURNING draft_id,revision,updated_at',
                      (Jsonb(body.document),body.draft_id,user['user_id'],body.expected_revision)).fetchone()
        if row:return row
        exists=c.execute('SELECT 1 FROM practice_admin_drafts WHERE draft_id=%s AND owner_id=%s',(body.draft_id,user['user_id'])).fetchone()
        if not exists:raise HTTPException(404,'Không tìm thấy bản nháp của bạn.')
        raise HTTPException(409,'Bản nháp đã được sửa ở cửa sổ khác. Tải lại bản nháp trước khi lưu.')


@router.post('/admin/reviews')
def propose(body: Review,user=Depends(require_admin)):
    doc=checked_document(body.document)
    with get_connection_pool().connection() as c:
        return c.execute('INSERT INTO practice_reviews(document,submitted_by) VALUES(%s,%s) RETURNING review_id,status',(Jsonb(doc),user['user_id'])).fetchone()


@router.post('/admin/reviews/{review_id}/{decision}')
def decide(review_id: int,decision: Literal['approve','reject'],user=Depends(require_admin)):
    with get_connection_pool().connection() as c,c.cursor() as cur:
        cur.execute('SELECT * FROM practice_reviews WHERE review_id=%s FOR UPDATE',(review_id,));row=cur.fetchone()
        if not row: raise HTTPException(404,'Không tìm thấy bản duyệt.')
        if row['status']!='pending': raise HTTPException(409,'Bản này đã được xử lý.')
        version=publish_document(cur,row['document']) if decision=='approve' else None
        cur.execute('UPDATE practice_reviews SET status=%s,reviewed_by=%s,reviewed_at=now(),published_version_id=%s WHERE review_id=%s',
                    ('approved' if version else 'rejected',user['user_id'],version,review_id))
        return {'status':'approved' if version else 'rejected','version_id':version}
