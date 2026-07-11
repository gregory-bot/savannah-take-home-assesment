"""
Booking service – business logic for appointment management.

All database writes happen inside a transaction so that the two-part
concurrency guard (SELECT FOR UPDATE on Doctor row + UNIQUE constraint)
works correctly.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.exceptions import ConflictError, NotFoundError, SlotUnavailableError, ValidationError
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.patient import Patient


def _supports_for_update(db: Session) -> bool:
    """Check if the database dialect supports SELECT ... FOR UPDATE."""
    return "sqlite" not in str(db.bind.url)


def _lock_doctor(db: Session, doctor_id: int):
    """Lock the doctor row if the DB supports it, otherwise just fetch."""
    query = db.query(Doctor).filter(Doctor.id == doctor_id)
    if _supports_for_update(db):
        query = query.with_for_update()
    doctor = query.first()
    if not doctor:
        raise NotFoundError("Doctor not found")
    return doctor


def get_doctor_or_404(db: Session, doctor_id: int) -> Doctor:
    """Get a doctor by ID or raise 404."""
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise NotFoundError("Doctor not found")
    return doctor


def get_patient_or_404(db: Session, patient_id: int) -> Patient:
    """Get a patient by ID or raise 404."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise NotFoundError("Patient not found")
    return patient


def _validate_slot_time(slot_time: datetime, doctor: Doctor):
    """Validate slot_time against business rules."""
    now = datetime.now(tz=timezone.utc)
    
    if slot_time <= now:
        raise ValidationError("slot_time must be in the future")
    
    if slot_time <= now + timedelta(hours=1):
        raise ValidationError("Appointment must be booked at least 1 hour in advance")
    
    if slot_time.minute not in (0, 30):
        raise ValidationError("slot_time must fall on a 30-minute boundary (XX:00 or XX:30)")
    
    # Check working hours
    slot_time_only = slot_time.time()
    if slot_time_only < doctor.work_start or slot_time_only >= doctor.work_end:
        raise ValidationError("slot_time falls outside the doctor's working hours")


def book_appointment(db: Session, doctor_id: int, patient_id: int, slot_time: datetime) -> Appointment:
    """Book an appointment with concurrency protection."""
    # Ensure UTC
    if slot_time.tzinfo is None:
        slot_time = slot_time.replace(tzinfo=timezone.utc)
    else:
        slot_time = slot_time.astimezone(timezone.utc)
    
    # Lock doctor row (or just fetch for SQLite)
    doctor = _lock_doctor(db, doctor_id)
    
    # Validate patient exists
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise NotFoundError("Patient not found")
    
    # Validate slot time
    _validate_slot_time(slot_time, doctor)
    
    # Check if slot is already booked (only active bookings)
    existing = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.slot_time == slot_time,
        Appointment.status == AppointmentStatus.booked
    ).first()
    
    if existing:
        raise SlotUnavailableError("This slot is already booked")
    
    # Check if there's a cancelled appointment for this slot and delete it
    cancelled = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.slot_time == slot_time,
        Appointment.status == AppointmentStatus.cancelled
    ).first()
    
    if cancelled:
        db.delete(cancelled)
        db.flush()
    
    # Create appointment
    appointment = Appointment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        slot_time=slot_time,
        status=AppointmentStatus.booked
    )
    db.add(appointment)
    db.flush()
    db.refresh(appointment)
    
    return appointment


def cancel_appointment(db: Session, appointment_id: int, reason: str) -> Appointment:
    """Cancel an existing appointment."""
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise NotFoundError("Appointment not found")
    
    if appointment.status == AppointmentStatus.cancelled:
        raise ConflictError("Appointment is already cancelled")
    
    appointment.status = AppointmentStatus.cancelled
    appointment.cancellation_reason = reason
    appointment.updated_at = datetime.now(tz=timezone.utc)
    
    db.flush()
    db.refresh(appointment)
    return appointment


def reschedule_appointment(db: Session, appointment_id: int, new_slot_time: datetime) -> Appointment:
    """Reschedule an existing appointment to a new slot."""
    # Ensure UTC
    if new_slot_time.tzinfo is None:
        new_slot_time = new_slot_time.replace(tzinfo=timezone.utc)
    else:
        new_slot_time = new_slot_time.astimezone(timezone.utc)
    
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise NotFoundError("Appointment not found")
    
    if appointment.status == AppointmentStatus.cancelled:
        raise ConflictError("Cannot reschedule a cancelled appointment")
    
    # Check if new slot is the same as current slot
    if appointment.slot_time.replace(tzinfo=timezone.utc) == new_slot_time:
        raise ValidationError("New slot time is the same as the current slot time")
    
    # Lock doctor row
    doctor = _lock_doctor(db, appointment.doctor_id)
    
    # Validate new slot time
    _validate_slot_time(new_slot_time, doctor)
    
    # Check if new slot is available (excluding current appointment, only active bookings)
    existing = db.query(Appointment).filter(
        Appointment.doctor_id == appointment.doctor_id,
        Appointment.slot_time == new_slot_time,
        Appointment.status == AppointmentStatus.booked,
        Appointment.id != appointment_id
    ).first()
    
    if existing:
        raise SlotUnavailableError("The new slot is already booked")
    
    # Check if there's a cancelled appointment for this new slot and delete it
    cancelled = db.query(Appointment).filter(
        Appointment.doctor_id == appointment.doctor_id,
        Appointment.slot_time == new_slot_time,
        Appointment.status == AppointmentStatus.cancelled,
        Appointment.id != appointment_id
    ).first()
    
    if cancelled:
        db.delete(cancelled)
        db.flush()
    
    # Update appointment
    appointment.slot_time = new_slot_time
    appointment.updated_at = datetime.now(tz=timezone.utc)
    
    db.flush()
    db.refresh(appointment)
    return appointment


def get_availability(db: Session, doctor_id: int, date_str: str) -> list[dict]:
    """Get available slots for a doctor on a specific date."""
    # Validate date
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError("Invalid date format. Use YYYY-MM-DD")
    
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise NotFoundError("Doctor not found")
    
    # Generate all possible slots for the day
    slots = []
    current_time = datetime.combine(date, doctor.work_start, tzinfo=timezone.utc)
    end_time = datetime.combine(date, doctor.work_end, tzinfo=timezone.utc)
    
    while current_time < end_time:
        # Check if slot is booked (only active bookings)
        booked = db.query(Appointment).filter(
            Appointment.doctor_id == doctor_id,
            Appointment.slot_time == current_time,
            Appointment.status == AppointmentStatus.booked
        ).first()
        
        slots.append({
            "slot_time": current_time.isoformat(),
            "available": not booked
        })
        
        current_time += timedelta(minutes=30)
    
    return slots


def get_patient_upcoming_appointments(db: Session, patient_id: int) -> list[Appointment]:
    """Get upcoming appointments for a patient, sorted by slot_time."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise NotFoundError("Patient not found")
    
    now = datetime.now(tz=timezone.utc)
    
    appointments = db.query(Appointment).filter(
        Appointment.patient_id == patient_id,
        Appointment.status == AppointmentStatus.booked,
        Appointment.slot_time > now
    ).order_by(Appointment.slot_time.asc()).all()
    
    return appointments