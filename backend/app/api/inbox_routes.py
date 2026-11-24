from uuid import UUID
from datetime import datetime,timezone
from fastapi import APIRouter, Depends, HTTPException
from app.auth import get_current_user
from app.database import get_connection_pool
from app.arena import notifications
from app.arena.practice_catalog import FAMILIES

router=APIRouter(prefix='/api/voice/inbox',tags=['simulated inbox'])


def owned(cur,sid,uid):
    cur.execute("""SELECT cs.ended_at,cs.case_parameters,v.definition,n.requested_action
                   FROM call_sessions cs JOIN scenario_versions v ON v.version_id=cs.scenario_version_id
                   JOIN dialogue_nodes n ON n.node_id=cs.current_node_id
                   WHERE cs.session_id=%s AND cs.user_id=%s FOR UPDATE OF cs""",(sid,uid))
    row=cur.fetchone()
    if not row: raise HTTPException(404,'Không tìm thấy hộp thư.')
    return row


@router.get('/{session_id}')
def inbox(session_id: UUID,user=Depends(get_current_user)):
    with get_connection_pool().connection() as c,c.cursor() as cur:
        row=owned(cur,session_id,user['user_id'])
        if not row['ended_at']:
            notifications.seed(cur,session_id,row['definition'],row['case_parameters'])
            notifications.request_artifact(cur,session_id,row['requested_action'])
        cur.execute('SELECT message_id,channel,sender,subject,body,code,created_at,expires_at,revoked_at,read_at FROM practice_messages WHERE session_id=%s ORDER BY message_id DESC',(session_id,))
        messages=cur.fetchall()
        now=datetime.now(timezone.utc)
        for message in messages:
            message['expired']=bool(message['expires_at'] and (message['expires_at']<=now or message['revoked_at']))
    return {'messages':messages,'can_resend':not row['ended_at'] and row['requested_action']=='share_sensitive'}


@router.post('/{session_id}/messages/{message_id}/read')
def read(session_id: UUID,message_id: int,user=Depends(get_current_user)):
    with get_connection_pool().connection() as c,c.cursor() as cur:
        row=owned(cur,session_id,user['user_id'])
        cur.execute('UPDATE practice_messages SET read_at=COALESCE(read_at,now()) WHERE session_id=%s AND message_id=%s RETURNING message_id',(session_id,message_id))
        if not cur.fetchone(): raise HTTPException(404,'Không tìm thấy thông báo.')
        if row['definition'].get('family') in FAMILIES and not row['ended_at']:
            cur.execute("INSERT INTO practice_events(session_id,event_type) VALUES(%s,'read_message') ON CONFLICT DO NOTHING",(session_id,))
    return {'read':True}


@router.post('/{session_id}/resend')
def resend(session_id: UUID,user=Depends(get_current_user)):
    with get_connection_pool().connection() as c,c.cursor() as cur:
        row=owned(cur,session_id,user['user_id'])
        if row['ended_at'] or row['requested_action']!='share_sensitive': raise HTTPException(409,'Hiện không có yêu cầu cấp mã.')
        notifications.otp(cur,session_id,resend=True)
    return {'sent':True}
