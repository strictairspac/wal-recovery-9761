from sqlalchemy import select
from src.models.entities import LogSet
from src.services.wal_engine import validate
from src.utils.serialize import record

def list_log_sets(db):return [record(x) for x in db.scalars(select(LogSet).order_by(LogSet.id))]
def create_log_set(db,data):
    values=data.model_dump();validate(values['initial'],values['records'])
    obj=LogSet(**values);db.add(obj);db.flush();return record(obj)
