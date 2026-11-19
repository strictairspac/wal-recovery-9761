import hashlib, hmac, os
from datetime import datetime, timedelta, timezone
import jwt
from src.config.settings import JWT_SECRET

def hash_password(password):
    salt = os.urandom(16).hex()
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 180000).hex()
    return salt + '$' + value

def verify_password(password, encoded):
    salt, expected = encoded.split('$')
    actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 180000).hex()
    return hmac.compare_digest(expected, actual)

def token(user):
    return jwt.encode({'sub': user.email, 'role': user.role, 'exp': datetime.now(timezone.utc) + timedelta(hours=8)}, JWT_SECRET, algorithm='HS256')
