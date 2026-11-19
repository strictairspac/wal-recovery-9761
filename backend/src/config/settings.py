import os
DATABASE_URL = os.environ['DATABASE_URL']
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
JWT_SECRET = os.environ['JWT_SECRET']
