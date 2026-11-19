from sqlalchemy import select
from fastapi import HTTPException
from src.models.entities import CrashCase,LogSet
from src.utils.serialize import record

def list_crash_cases(db):return [record(x) for x in db.scalars(select(CrashCase).order_by(CrashCase.id))]
def create_crash_case(db,data):
    logs=db.get(LogSet,data.log_set_id)
    if logs is None:raise HTTPException(404,'日志集不存在')
    if data.crash_after>len(logs.records):raise HTTPException(422,'崩溃点超过日志条数')
    obj=CrashCase(**data.model_dump());db.add(obj);db.flush();return record(obj)
