import json
from fastapi import APIRouter,Depends
from fastapi.responses import Response
from src.config.database import get_db
from src.middlewares.auth import current_user,writable
from src.schemas.recovery import RecoveryInput
from src.services.recovery_service import list_recoveries,get_recovery,create_recovery
from src.controllers.actions import audit
from src.utils.serialize import record
router=APIRouter()
@router.get('/recoveries')
def listing(db=Depends(get_db),user=Depends(current_user)):return list_recoveries(db)
@router.post('/recoveries',status_code=202)
def create(data:RecoveryInput,db=Depends(get_db),user=Depends(writable)):
    obj=create_recovery(db,data);audit(db,user,f'recovery:enqueue:{obj.id}');db.commit();return record(obj)
@router.get('/recoveries/{ident}')
def detail(ident:int,db=Depends(get_db),user=Depends(current_user)):return record(get_recovery(db,ident))
@router.get('/recoveries/{ident}/export')
def export(ident:int,db=Depends(get_db),user=Depends(current_user)):
    obj=get_recovery(db,ident)
    return Response(json.dumps(record(obj),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="recovery-{ident}.json"'})
