from fastapi import APIRouter, Depends, HTTPException
from src.config.database import get_db
from src.middlewares.auth import current_user,writable
from src.schemas.log_set import LogSetInput
from src.services.log_set_service import list_log_sets,create_log_set
from src.controllers.actions import audit
router=APIRouter()
@router.get('/log-sets')
def listing(db=Depends(get_db),user=Depends(current_user)):return list_log_sets(db)
@router.post('/log-sets',status_code=201)
def create(data:LogSetInput,db=Depends(get_db),user=Depends(writable)):
    try:out=create_log_set(db,data)
    except ValueError as exc:raise HTTPException(422,str(exc))
    audit(db,user,'log_set:create');db.commit();return out
