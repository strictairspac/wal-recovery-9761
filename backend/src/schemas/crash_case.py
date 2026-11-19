from pydantic import BaseModel, Field
class CrashCaseInput(BaseModel):
    name: str=Field(min_length=2,max_length=100)
    log_set_id: int=Field(gt=0)
    crash_after: int=Field(ge=0,le=200)
