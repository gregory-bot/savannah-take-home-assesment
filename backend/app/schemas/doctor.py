from datetime import time

from pydantic import BaseModel, ConfigDict


class DoctorBase(BaseModel):
    full_name: str
    specialization: str
    work_start: time
    work_end: time


class DoctorCreate(DoctorBase):
    pass


class DoctorResponse(DoctorBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class SlotResponse(BaseModel):
    slot_time: str
    available: bool
