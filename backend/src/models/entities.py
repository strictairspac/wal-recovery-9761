from datetime import datetime, timezone
from sqlalchemy import String, Integer, JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    email: Mapped[str]=mapped_column(String(120),unique=True)
    role: Mapped[str]=mapped_column(String(20))
    password_hash: Mapped[str]=mapped_column(String(250))
class LogSet(Base):
    __tablename__='log_sets'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(100),unique=True)
    initial: Mapped[dict]=mapped_column(JSON)
    records: Mapped[list]=mapped_column(JSON)
    description: Mapped[str]=mapped_column(String(500))
class CrashCase(Base):
    __tablename__='crash_cases'
    id: Mapped[int]=mapped_column(primary_key=True)
    log_set_id: Mapped[int]=mapped_column(ForeignKey('log_sets.id'))
    name: Mapped[str]=mapped_column(String(100),unique=True)
    crash_after: Mapped[int]=mapped_column(Integer)
class Recovery(Base):
    __tablename__='recoveries'
    id: Mapped[int]=mapped_column(primary_key=True)
    crash_case_id: Mapped[int]=mapped_column(ForeignKey('crash_cases.id'))
    label: Mapped[str]=mapped_column(String(120))
    status: Mapped[str]=mapped_column(String(20),default='queued')
    snapshot: Mapped[dict]=mapped_column(JSON)
    result: Mapped[dict | None]=mapped_column(JSON,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
class Audit(Base):
    __tablename__='audits'
    id: Mapped[int]=mapped_column(primary_key=True)
    actor: Mapped[str]=mapped_column(String(120))
    action: Mapped[str]=mapped_column(String(120))
    created_at: Mapped[datetime]=mapped_column(DateTime,default=now)
