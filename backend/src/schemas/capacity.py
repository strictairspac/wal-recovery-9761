from pydantic import BaseModel, Field
from src.services.capacity_engine import CAPACITY_MAX, VALUE_LIMIT


class CapacityDrillInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    initial: dict[str, int] = Field(min_length=1, max_length=30)
    capacity_bytes: int = Field(ge=1, le=CAPACITY_MAX)
    short_threshold_bytes: int | None = Field(default=None, ge=1, le=CAPACITY_MAX)
    description: str = Field(default='', max_length=500)


class SampleRequestInput(BaseModel):
    code: str = Field(min_length=1, max_length=30, pattern=r'^[A-Za-z0-9_-]+$')
    declared_bytes: int = Field(ge=1, le=CAPACITY_MAX)


class SampleWriteInput(BaseModel):
    key: str = Field(min_length=1, max_length=50, pattern=r'^[A-Za-z0-9_-]+$')
    value: int = Field(ge=-VALUE_LIMIT, le=VALUE_LIMIT)
    payload_bytes: int = Field(ge=1, le=CAPACITY_MAX)


class CrashInput(BaseModel):
    crash_after: int | None = Field(default=None, ge=0)
