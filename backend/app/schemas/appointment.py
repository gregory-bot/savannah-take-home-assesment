from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.appointment import AppointmentStatus
from app.schemas.doctor import DoctorResponse
from app.schemas.patient import PatientResponse


class AppointmentCreate(BaseModel):
    doctor_id: int
    patient_id: int
    slot_time: datetime


class AppointmentCancelRequest(BaseModel):
    reason: str


class AppointmentRescheduleRequest(BaseModel):
    new_slot_time: datetime


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    patient_id: int
    slot_time: datetime
    status: AppointmentStatus
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime
    doctor: DoctorResponse
    patient: PatientResponse
