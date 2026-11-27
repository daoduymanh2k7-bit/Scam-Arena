"""Account administration without passwords or private conversation contents."""
from typing import Literal
from datetime import datetime,timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel,Field
from app.auth import require_admin
from app.database import get_connection_pool

router=APIRouter(prefix='/api/admin/users',tags=['user administration'])

class AccountStatus(BaseModel):
    locked: bool
    expected_locked: bool
    reason: str = Field(default='',max_length=500)


@router.get('')
def list_users(search: str=Query(default='',max_length=64), state: Literal['all','active','locked']='all',
               role: Literal['all','user','admin']='all', page: int=Query(default=1,ge=1,le=10000),
               page_size: int=Query(default=25,ge=1,le=100), user=Depends(require_admin), response: Response=None):
    if response is not None:response.headers["Cache-Control"]="no-store"
    where="WHERE position(lower(%s) in lower(u.username))>0 AND (%s='all' OR u.is_locked=(%s='locked')) AND (%s='all' OR u.role=%s)"
    args=(search.strip(),state,state,role,role)
    with get_connection_pool().connection() as c:
        total=c.execute('SELECT count(*) AS n FROM app_users u '+where,args).fetchone()['n']
        admins=c.execute("SELECT count(*) AS n FROM app_users WHERE role='admin' AND NOT is_locked").fetchone()['n']
        rows=c.execute("""SELECT u.user_id,u.username,u.role,u.created_at,u.last_login_at,u.is_locked,u.locked_at,u.lock_reason,
                   stats.sessions,stats.turns,stats.finished,stats.reviewed,stats.correct,stats.avg_score,stats.last_practice_at
             FROM app_users u
             LEFT JOIN LATERAL (
                SELECT count(*) AS sessions,COALESCE(sum(cs.turn_no),0) AS turns,
                       count(*) FILTER(WHERE cs.ended_at IS NOT NULL) AS finished,
                       count(j.session_id) AS reviewed,
                       count(*) FILTER(WHERE j.judgement=v.definition->>'scenario_kind') AS correct,
                       round(avg(CASE WHEN j.evaluation->>'evaluation_score' IS NOT NULL THEN (j.evaluation->>'evaluation_score')::numeric
                                 WHEN cs.ended_at IS NOT NULL AND COALESCE(v.definition->>'family','legacy') NOT IN ('delivery','appointment','support') THEN cs.total_score END),1) AS avg_score,
                       max(cs.started_at) AS last_practice_at
                  FROM call_sessions cs LEFT JOIN practice_judgements j USING(session_id)
                  LEFT JOIN scenario_versions v ON v.version_id=cs.scenario_version_id WHERE cs.user_id=u.user_id
             ) stats ON true """+where+' ORDER BY u.created_at DESC,u.user_id LIMIT %s OFFSET %s',args+(page_size,(page-1)*page_size)).fetchall()
    for row in rows:
        row['can_lock']=row['user_id']!=user['user_id'] and (row['role']!='admin' or admins>1)
    return {'users':rows,'total':total,'page':page,'page_size':page_size,'current_user_id':user['user_id'],'checked_at':datetime.now(timezone.utc).isoformat()}


@router.get('/{user_id}/events')
def user_events(user_id: str, user=Depends(require_admin)):
    with get_connection_pool().connection() as c:
        if not c.execute('SELECT 1 FROM app_users WHERE user_id=%s',(user_id,)).fetchone():raise HTTPException(404,'Không tìm thấy tài khoản.')
        return c.execute('SELECT event_id,actor_username,target_username,action,reason,created_at FROM admin_user_events WHERE target_id=%s ORDER BY event_id DESC LIMIT 50',(user_id,)).fetchall()


@router.post('/{user_id}/status')
def change_status(user_id: str,body: AccountStatus,user=Depends(require_admin)):
    reason=body.reason.strip()
    if body.locked and len(reason)<3:raise HTTPException(422,'Nhập lý do khóa tối thiểu 3 ký tự.')
    with get_connection_pool().connection() as c:
        # Serialize moderation changes, including two admins trying to lock each other.
        c.execute('SELECT pg_advisory_xact_lock(736219042)')
        actor=c.execute('SELECT user_id,username,role,is_locked FROM app_users WHERE user_id=%s FOR UPDATE',(user['user_id'],)).fetchone()
        if not actor or actor['role']!='admin' or actor['is_locked']:raise HTTPException(403,'Quyền quản trị không còn hiệu lực.')
        target=c.execute('SELECT user_id,username,role,is_locked FROM app_users WHERE user_id=%s FOR UPDATE',(user_id,)).fetchone()
        if not target:raise HTTPException(404,'Không tìm thấy tài khoản.')
        if body.locked and user_id==actor['user_id']:raise HTTPException(409,'Không thể tự khóa tài khoản đang sử dụng.')
        if target['is_locked']!=body.expected_locked:raise HTTPException(409,'Trạng thái đã thay đổi. Tải lại danh sách trước khi thao tác.')
        if target['is_locked']==body.locked:return {'changed':False,'is_locked':body.locked}
        if body.locked and target['role']=='admin':
            count=c.execute("SELECT count(*) AS n FROM app_users WHERE role='admin' AND NOT is_locked").fetchone()['n']
            if count<=1:raise HTTPException(409,'Không thể khóa quản trị viên cuối cùng.')
        c.execute('UPDATE app_users SET is_locked=%s,locked_at=CASE WHEN %s THEN now() ELSE NULL END,lock_reason=%s WHERE user_id=%s',
                  (body.locked,body.locked,reason if body.locked else '',user_id))
        if body.locked:c.execute('DELETE FROM auth_sessions WHERE user_id=%s',(user_id,))
        event=c.execute('INSERT INTO admin_user_events(actor_id,target_id,actor_username,target_username,action,reason) VALUES(%s,%s,%s,%s,%s,%s) RETURNING event_id',
                       (actor['user_id'],user_id,actor['username'],target['username'],'lock' if body.locked else 'unlock',reason)).fetchone()
    return {'changed':True,'is_locked':body.locked,'event_id':event['event_id']}
