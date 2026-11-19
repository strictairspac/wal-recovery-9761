from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from src.config.database import get_db
from src.models.entities import User
from src.utils.security import verify_password, token
router = APIRouter()
class Credentials(BaseModel):
    email: str = Field(max_length=120)
    password: str = Field(max_length=200)
@router.post('/auth/login')
def login(data: Credentials, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    if not user or not verify_password(data.password, user.password_hash): raise HTTPException(401, '账号或密码错误')
    return {'access_token': token(user), 'role': user.role, 'email': user.email}
