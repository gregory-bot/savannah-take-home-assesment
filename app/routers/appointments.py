from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.appointment import (
    AppointmentCancelRequest,
    AppointmentCreate,
    AppointmentRescheduleRequest,
    AppointmentResponse,
)
from app.services import booking

router = APIRouter(prefix="/appointments", tags=["Appointments"])


@router.post("", response_model=AppointmentResponse, status_code=201)
def book_appointment(payload: AppointmentCreate, db: Session = Depends(get_db)):
    """
    Book a 30-minute appointment slot.

    Validates that the slot:
    - Falls within the doctor's working hours
    - Is not in the past
    - Is at least 1 hour from now
    - Aligns to the 30-minute grid (XX:00 or XX:30)
    - Is not already taken

    The booking is protected against concurrent double-booking via SELECT FOR UPDATE
    and a UNIQUE database constraint on (doctor_id, slot_time).
    """
    appointment = booking.book_appointment(
        db,
        doctor_id=payload.doctor_id,
        patient_id=payload.patient_id,
        slot_time=payload.slot_time,
    )
    db.commit()
    db.refresh(appointment)
    return appointment


@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(appointment_id: int, db: Session = Depends(get_db)):
    """Get a single appointment by ID."""
    return booking.get_appointment_or_404(db, appointment_id)


@router.patch("/{appointment_id}/cancel", response_model=AppointmentResponse)
def cancel_appointment(
    appointment_id: int,
    payload: AppointmentCancelRequest,
    db: Session = Depends(get_db),
):
    """
    Cancel an appointment.  The slot becomes available for others to book.
    Returns 409 if the appointment is already cancelled.
    """
    appointment = booking.cancel_appointment(db, appointment_id, payload.reason)
    db.commit()
    db.refresh(appointment)
    return appointment


@router.patch("/{appointment_id}/reschedule", response_model=AppointmentResponse)
def reschedule_appointment(
    appointment_id: int,
    payload: AppointmentRescheduleRequest,
    db: Session = Depends(get_db),
):
    """
    Move an appointment to a new slot.

    The original slot is freed and the new slot is validated identically to a fresh
    booking. Both operations happen atomically — if the new slot is unavailable the
    original booking is preserved.

    Returns 409 if the appointment is already cancelled or the new slot is taken.
    """
    appointment = booking.reschedule_appointment(db, appointment_id, payload.new_slot_time)
    db.commit()
    db.refresh(appointment)
    return appointment
