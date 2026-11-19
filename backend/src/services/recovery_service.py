from sqlalchemy import select
from fastapi import HTTPException
from src.models.entities import Recovery,CrashCase,LogSet
from src.utils.serialize import record

def list_recoveries(db):return [record(x) for x in db.scalars(select(Recovery).order_by(Recovery.id.desc()).limit(100))]
def get_recovery(db,ident):
    obj=db.get(Recovery,ident)
    if obj is None:raise HTTPException(404,'恢复记录不存在')
    return obj
def create_recovery(db,data):
    case=db.get(CrashCase,data.crash_case_id)
    if case is None:raise HTTPException(404,'故障场景不存在')
    if len(db.scalars(select(Recovery.id).where(Recovery.status.in_(['queued','running']))).all())>=20:raise HTTPException(429,'待处理配额20已满')
    logs=db.get(LogSet,case.log_set_id)
    obj=Recovery(**data.model_dump(),status='queued',snapshot={'log_set':record(logs),'case':record(case)})
    db.add(obj);db.flush();return obj
