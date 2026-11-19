import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from src.config.settings import JWT_SECRET
from src.config.database import get_db
from src.models.entities import User
from sqlalchemy import select
bearer = HTTPBearer(auto_error=False)
def current_user(credentials=Depends(bearer), db=Depends(get_db)):
    try:
        if not credentials: raise ValueError('missing bearer')
        claims = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=['HS256'])
        user = db.scalar(select(User).where(User.email == claims['sub']))
        if not user: raise ValueError('unknown user')
        return user
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, '登录已失效，请重新登录')
def writable(user=Depends(current_user)):
    if user.role not in ('admin', 'operator'): raise HTTPException(403, '观察员仅可查看和导出')
    return user
def admin(user=Depends(current_user)):
    if user.role != 'admin': raise HTTPException(403, '审计仅管理员可查看')
    return user
