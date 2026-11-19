from fastapi import FastAPI, Depends
from sqlalchemy import select, text
from redis import Redis
from src.config.database import get_db
from src.config.settings import REDIS_URL
from src.middlewares.errors import ErrorMiddleware
from src.middlewares.request_id import RequestIdMiddleware
from src.middlewares.auth import admin
from src.models.entities import Audit
from src.utils.serialize import record
from src.routes import auth, log_sets, crash_cases, recoveries
app = FastAPI(title='采样账本 WAL 恢复演练')
app.add_middleware(ErrorMiddleware)
app.add_middleware(RequestIdMiddleware)
for module in (auth, log_sets, crash_cases, recoveries): app.include_router(module.router)
@app.get('/health')
def health(db=Depends(get_db)):
    db.execute(text('SELECT 1')); Redis.from_url(REDIS_URL).ping()
    return {'status': 'ok'}
@app.get('/audits')
def audits(db=Depends(get_db), user=Depends(admin)):
    return [record(a) for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(100))]
