from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.schemas.doctor import DoctorCreate, DoctorResponse, SlotResponse
from app.services import booking

router = APIRouter(prefix="/doctors", tags=["Doctors"])


@router.post("", response_model=DoctorResponse, status_code=201)
def create_doctor(payload: DoctorCreate, db: Session = Depends(get_db)):
    """Register a new doctor with their working hours."""
    if payload.work_start >= payload.work_end:
        from app.exceptions import ValidationError
        raise ValidationError("work_start must be before work_end.")

    doctor = Doctor(**payload.model_dump())
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return doctor


@router.get("", response_model=list[DoctorResponse])
def list_doctors(db: Session = Depends(get_db)):
    """List all registered doctors."""
    return db.query(Doctor).all()


@router.get("/{doctor_id}", response_model=DoctorResponse)
def get_doctor(doctor_id: int, db: Session = Depends(get_db)):
    """Get a single doctor by ID."""
    return booking.get_doctor_or_404(db, doctor_id)


@router.get("/{doctor_id}/availability", response_model=list[SlotResponse])
def get_availability(
    doctor_id: int,
    date: str = Query(..., description="Date in YYYY-MM-DD format (UTC)"),
    db: Session = Depends(get_db),
):
    """
    Return all 30-minute slots for a doctor on a given date.
    Slots already booked or within 1 hour of now are marked unavailable.
    """
    return booking.get_availability(db, doctor_id, date)
