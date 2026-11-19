from typing import Literal
from pydantic import BaseModel, Field
class WalRecord(BaseModel):
    op: Literal['begin','write','commit','abort','checkpoint']
    tx: str | None = Field(default=None,max_length=30,pattern=r'^[A-Za-z0-9_-]+$')
    key: str | None = Field(default=None,max_length=50,pattern=r'^[A-Za-z0-9_-]+$')
    value: int | None = Field(default=None,ge=-1000000000,le=1000000000)
class LogSetInput(BaseModel):
    name: str=Field(min_length=2,max_length=100)
    initial: dict[str,int]=Field(min_length=1,max_length=30)
    records: list[WalRecord]=Field(min_length=1,max_length=200)
    description: str=Field(default='',max_length=500)
