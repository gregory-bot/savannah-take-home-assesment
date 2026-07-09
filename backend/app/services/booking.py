"""
Core booking logic.

Concurrency strategy
--------------------
We rely on TWO layers of protection:

1. SELECT FOR UPDATE on the doctor row (PostgreSQL only) — serialises concurrent
   requests so that the availability check and the INSERT are effectively atomic
   within the same database transaction.

2. A UNIQUE constraint on (doctor_id, slot_time) at the database level — this is
   the final, unconditional guard. Even if two requests somehow bypass the row
   lock (e.g. different transactions, or during testing with SQLite which does not
   support SELECT FOR UPDATE), the database constraint will reject the second
   INSERT and we surface a 409.

Together these two layers prevent the classic TOCTOU race: check-then-insert with
no lock between them.
"""

from datetime import date as date_type
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, NotFoundError, SlotUnavailableError, ValidationError
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.patient import Patient

SLOT_DURATION = timedelta(minutes=30)
BOOKING_HORIZON = timedelta(hours=1)  # cannot book within 1 hour of now


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _supports_for_update(db: Session) -> bool:
    """SELECT FOR UPDATE is only reliable on PostgreSQL in this setup."""
    try:
        return db.bind.dialect.name == "postgresql"
    except Exception:
        return False


def _validate_slot_time(slot_time: datetime, doctor: Doctor) -> None:
    """Raise ValidationError if slot_time is not bookable for this doctor."""
    if slot_time.tzinfo is None:
        raise ValidationError("slot_time must include timezone information (use UTC).")

    slot_utc = slot_time.astimezone(timezone.utc)
    now = _now_utc()

    if slot_utc <= now:
        raise ValidationError("Cannot book a slot in the past.")

    if slot_utc < now + BOOKING_HORIZON:
        raise ValidationError("Bookings must be made at least 1 hour in advance.")

    if slot_utc.second != 0 or slot_utc.microsecond != 0:
        raise ValidationError("Slot time must start on a whole minute.")

    if slot_utc.minute not in (0, 30):
        raise ValidationError("Slots must start on the hour or half-hour (30-minute grid).")

    slot_local_time = slot_utc.time().replace(tzinfo=None)
    if slot_local_time < doctor.work_start or slot_local_time >= doctor.work_end:
        raise ValidationError(
            f"Slot {slot_utc.strftime('%H:%M')} UTC is outside "
            f"Dr. {doctor.full_name}'s working hours "
            f"({doctor.work_start.strftime('%H:%M')}–{doctor.work_end.strftime('%H:%M')} UTC)."
        )


def get_doctor_or_404(db: Session, doctor_id: int) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise NotFoundError("Doctor", doctor_id)
    return doctor


def get_patient_or_404(db: Session, patient_id: int) -> Patient:
    patient = db.get(Patient, patient_id)
    if not patient:
        raise NotFoundError("Patient", patient_id)
    return patient


def get_appointment_or_404(db: Session, appointment_id: int) -> Appointment:
    appointment = db.get(Appointment, appointment_id)
    if not appointment:
        raise NotFoundError("Appointment", appointment_id)
    return appointment


def get_availability(db: Session, doctor_id: int, date_str: str) -> list[dict]:
    """Return every 30-minute slot on `date_str` with its availability status."""
    doctor = get_doctor_or_404(db, doctor_id)

    try:
        query_date = date_type.fromisoformat(date_str)
    except ValueError:
        raise ValidationError("Invalid date format. Use YYYY-MM-DD.")

    day_start = datetime.combine(query_date, doctor.work_start, tzinfo=timezone.utc)
    day_end = datetime.combine(query_date, doctor.work_end, tzinfo=timezone.utc)

    booked_times: set[datetime] = set(
        db.scalars(
            select(Appointment.slot_time).where(
                Appointment.doctor_id == doctor_id,
                Appointment.slot_time >= day_start,
                Appointment.slot_time < day_end,
                Appointment.status == AppointmentStatus.booked,
            )
        ).all()
    )

    now = _now_utc()
    slots: list[dict] = []
    current = day_start
    while current < day_end:
        available = current not in booked_times and current > now + BOOKING_HORIZON
        slots.append({"slot_time": current.isoformat(), "available": available})
        current += SLOT_DURATION

    return slots


def book_appointment(
    db: Session,
    doctor_id: int,
    patient_id: int,
    slot_time: datetime,
) -> Appointment:
    """
    Book a slot.

    On PostgreSQL we issue SELECT FOR UPDATE on the doctor row to serialise
    concurrent requests before the check-then-insert.  The UNIQUE constraint
    on (doctor_id, slot_time) acts as a backstop for any races that slip through.
    """
    if _supports_for_update(db):
        doctor = db.scalars(
            select(Doctor).where(Doctor.id == doctor_id).with_for_update()
        ).first()
    else:
        doctor = db.get(Doctor, doctor_id)

    if not doctor:
        raise NotFoundError("Doctor", doctor_id)

    get_patient_or_404(db, patient_id)

    slot_utc = (
        slot_time.astimezone(timezone.utc)
        if slot_time.tzinfo
        else slot_time.replace(tzinfo=timezone.utc)
    )
    _validate_slot_time(slot_utc, doctor)

    existing = db.scalars(
        select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.slot_time == slot_utc,
            Appointment.status == AppointmentStatus.booked,
        )
    ).first()
    if existing:
        raise SlotUnavailableError(
            f"The slot at {slot_utc.strftime('%Y-%m-%d %H:%M')} UTC is already booked."
        )

    appointment = Appointment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        slot_time=slot_utc,
        status=AppointmentStatus.booked,
    )
    db.add(appointment)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise SlotUnavailableError(
            f"The slot at {slot_utc.strftime('%Y-%m-%d %H:%M')} UTC was just taken by another booking."
        )

    db.refresh(appointment)
    return appointment


def cancel_appointment(db: Session, appointment_id: int, reason: str) -> Appointment:
    appointment = get_appointment_or_404(db, appointment_id)

    if appointment.status == AppointmentStatus.cancelled:
        raise ConflictError("Appointment is already cancelled.")

    appointment.status = AppointmentStatus.cancelled
    appointment.cancellation_reason = reason
    appointment.updated_at = _now_utc()
    db.flush()
    db.refresh(appointment)
    return appointment


def reschedule_appointment(
    db: Session,
    appointment_id: int,
    new_slot_time: datetime,
) -> Appointment:
    """
    Move an appointment to a new slot.

    Both the release of the old slot and the acquisition of the new one happen
    inside a single database transaction.  If the new slot is unavailable the
    transaction is rolled back and the patient keeps their original booking.
    """
    if _supports_for_update(db):
        appointment = db.scalars(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .with_for_update()
        ).first()
    else:
        appointment = db.get(Appointment, appointment_id)

    if not appointment:
        raise NotFoundError("Appointment", appointment_id)

    if appointment.status == AppointmentStatus.cancelled:
        raise ConflictError("Cannot reschedule a cancelled appointment.")

    if _supports_for_update(db):
        doctor = db.scalars(
            select(Doctor).where(Doctor.id == appointment.doctor_id).with_for_update()
        ).first()
    else:
        doctor = db.get(Doctor, appointment.doctor_id)

    new_slot_utc = (
        new_slot_time.astimezone(timezone.utc)
        if new_slot_time.tzinfo
        else new_slot_time.replace(tzinfo=timezone.utc)
    )

    if new_slot_utc == appointment.slot_time:
        raise ValidationError("The new slot time is the same as the current slot.")

    _validate_slot_time(new_slot_utc, doctor)

    conflict = db.scalars(
        select(Appointment).where(
            Appointment.doctor_id == appointment.doctor_id,
            Appointment.slot_time == new_slot_utc,
            Appointment.status == AppointmentStatus.booked,
            Appointment.id != appointment_id,
        )
    ).first()
    if conflict:
        raise SlotUnavailableError(
            f"The slot at {new_slot_utc.strftime('%Y-%m-%d %H:%M')} UTC is already booked."
        )

    appointment.slot_time = new_slot_utc
    appointment.updated_at = _now_utc()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise SlotUnavailableError(
            f"The slot at {new_slot_utc.strftime('%Y-%m-%d %H:%M')} UTC was just taken by another booking."
        )

    db.refresh(appointment)
    return appointment


def get_patient_upcoming_appointments(db: Session, patient_id: int) -> list[Appointment]:
    """Return upcoming booked appointments for a patient, sorted by slot time."""
    get_patient_or_404(db, patient_id)
    now = _now_utc()
    return list(
        db.scalars(
            select(Appointment)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.slot_time > now,
                Appointment.status == AppointmentStatus.booked,
            )
            .order_by(Appointment.slot_time)
        ).all()
    )
