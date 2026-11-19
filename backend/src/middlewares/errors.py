import logging
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware
class ErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try: return await call_next(request)
        except IntegrityError:
            return JSONResponse({'detail': '名称已存在或关联数据无效，请修改后重试'}, status_code=409)
        except Exception:
            logging.exception('request failed')
            return JSONResponse({'detail': '服务暂时不可用，请稍后重试'}, status_code=500)
