import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from src.config.database import get_db
from src.controllers.actions import audit
from src.middlewares.auth import current_user, writable
from src.schemas.capacity import CapacityDrillInput, CrashInput, SampleRequestInput, SampleWriteInput
from src.services import capacity_service
from src.utils.serialize import record

router = APIRouter()


@router.get('/capacity-drills')
def listing(db=Depends(get_db), user=Depends(current_user)):
    return capacity_service.list_drills(db)


@router.post('/capacity-drills', status_code=201)
def create(data: CapacityDrillInput, db=Depends(get_db), user=Depends(writable)):
    obj = capacity_service.create_drill(db, data)
    audit(db, user, f'capacity_drill:create:{obj.id}')
    db.commit()
    return record(obj)


@router.get('/capacity-drills/{ident}')
def detail(ident: int, db=Depends(get_db), user=Depends(current_user)):
    return capacity_service.detail(db, ident)


@router.post('/capacity-drills/{ident}/requests', status_code=202)
def enqueue(ident: int, data: SampleRequestInput, db=Depends(get_db), user=Depends(writable)):
    try:
        req = capacity_service.enqueue(db, ident, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit(db, user, f'capacity_request:enqueue:{req.code}')
    db.commit()
    return record(req)


@router.post('/capacity-drills/{ident}/requests/{code}/writes', status_code=201)
def write_sample(ident: int, code: str, data: SampleWriteInput,
                 db=Depends(get_db), user=Depends(writable)):
    req = capacity_service.write_sample(db, ident, code, data)
    audit(db, user, f'capacity_request:write:{code}')
    db.commit()
    return record(req)


@router.post('/capacity-drills/{ident}/requests/{code}/commit')
def commit_request(ident: int, code: str, db=Depends(get_db), user=Depends(writable)):
    req = capacity_service.finish(db, ident, code, 'commit')
    audit(db, user, f'capacity_request:commit:{code}')
    db.commit()
    return record(req)


@router.post('/capacity-drills/{ident}/requests/{code}/abort')
def abort_request(ident: int, code: str, db=Depends(get_db), user=Depends(writable)):
    req = capacity_service.finish(db, ident, code, 'abort')
    audit(db, user, f'capacity_request:abort:{code}')
    db.commit()
    return record(req)


@router.post('/capacity-drills/{ident}/checkpoint')
def checkpoint(ident: int, db=Depends(get_db), user=Depends(writable)):
    try:
        drill = capacity_service.checkpoint(db, ident)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit(db, user, f'capacity_drill:checkpoint:{ident}')
    db.commit()
    return record(drill)


@router.post('/capacity-drills/{ident}/crash')
def crash(ident: int, data: CrashInput, db=Depends(get_db), user=Depends(writable)):
    try:
        drill = capacity_service.crash(db, ident, data.crash_after)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit(db, user, f'capacity_drill:crash:{ident}')
    db.commit()
    return capacity_service.detail(db, ident)


@router.get('/capacity-drills/{ident}/export')
def export(ident: int, db=Depends(get_db), user=Depends(current_user)):
    bundle = capacity_service.export_bundle(db, ident)
    return Response(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        media_type='application/json',
        headers={'Content-Disposition': f'attachment; filename="capacity-drill-{ident}.json"'})
