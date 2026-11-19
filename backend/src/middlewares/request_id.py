import uuid
from starlette.middleware.base import BaseHTTPMiddleware
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers['X-Request-ID'] = uuid.uuid4().hex
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
