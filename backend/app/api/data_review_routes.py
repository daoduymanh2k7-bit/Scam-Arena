from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from app.auth import require_admin
from app.database import get_connection_pool
from app.arena import data_review
from app.arena.review_llm import configured

router=APIRouter(prefix='/api/admin/data-review',tags=['data review'])


class Run(BaseModel):
    limit:int=Field(default=5,ge=1,le=20)
    kind:Literal['all','intent','rule','stale_session','duplicate','dialogue']='all'


class Decision(BaseModel):
    decision:Literal['accepted','rejected']
    expected_hash:str=Field(min_length=64,max_length=64)
    intent:Literal['verify','refuse','doubt','comply','share_sensitive','transfer_money','hang_up','unknown']|None=None
    corrected_text:str|None=Field(default=None,max_length=2000)
    note:str=Field(default='',max_length=1000)


@router.get('')
def queue(response:Response,decision:Literal['pending','accepted','rejected','all']='pending',
          kind:Literal['all','intent','rule','stale_session','duplicate','dialogue']='all',
          page:int=Query(default=1,ge=1),user=Depends(require_admin)):
    response.headers['Cache-Control']='no-store'
    with get_connection_pool().connection() as c:
        items=c.execute('''SELECT * FROM data_review_items WHERE (%s='all' OR decision=%s) AND (%s='all' OR kind=%s)
           ORDER BY CASE WHEN analysis_status='ready' THEN 0 ELSE 1 END,item_id DESC LIMIT 20 OFFSET %s''',
           (decision,decision,kind,kind,(page-1)*20)).fetchall()
        total=c.execute("SELECT count(*) n FROM data_review_items WHERE (%s='all' OR decision=%s) AND (%s='all' OR kind=%s)",(decision,decision,kind,kind)).fetchone()['n']
        counts=c.execute('SELECT decision,count(*) n FROM data_review_items GROUP BY decision').fetchall()
        run=c.execute("SELECT *,updated_at<now()-interval '10 minutes' AS stale FROM data_review_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    return {'items':items,'total':total,'counts':counts,'run':run,'page':page,'llm_configured':configured()}


@router.post('/run',status_code=202)
def run(body:Run,background_tasks:BackgroundTasks,user=Depends(require_admin)):
    run_id,created=data_review.create_run(user['user_id'])
    if created:background_tasks.add_task(data_review.run_review,run_id,body.limit,kind=body.kind)
    return {'run_id':run_id,'started':created}


@router.post('/items/{item_id}/decision')
def decide(item_id:int,body:Decision,user=Depends(require_admin)):
    try:return data_review.decide(item_id,body,user['user_id'])
    except KeyError:raise HTTPException(404,'Không tìm thấy đề xuất.')
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))
