from fastapi import APIRouter, Depends, HTTPException
from src.config.database import get_db
from src.middlewares.auth import current_user,writable
from src.schemas.crash_case import CrashCaseInput
from src.services.crash_case_service import list_crash_cases,create_crash_case
from src.controllers.actions import audit
router=APIRouter()
@router.get('/crash-cases')
def listing(db=Depends(get_db),user=Depends(current_user)):return list_crash_cases(db)
@router.post('/crash-cases',status_code=201)
def create(data:CrashCaseInput,db=Depends(get_db),user=Depends(writable)):
    try:out=create_crash_case(db,data)
    except ValueError as exc:raise HTTPException(422,str(exc))
    audit(db,user,'crash_case:create');db.commit();return out
