"""
Tests for the core booking logic.

Covers happy paths, validation, and edge cases. Tests run against an
in-memory SQLite database (see conftest.py).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.exceptions import ConflictError, SlotUnavailableError, ValidationError
from app.models.appointment import AppointmentStatus
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.services import booking


def _future_slot(hours_ahead: int = 2, minute: int = 0) -> datetime:
    """Return a UTC datetime that is `hours_ahead` from now, on a 30-minute boundary."""
    now = datetime.now(tz=timezone.utc)
    base = now + timedelta(hours=hours_ahead)
    return base.replace(minute=minute, second=0, microsecond=0)


def make_doctor(db, work_start="09:00", work_end="17:00"):
    from datetime import time
    start_h, start_m = map(int, work_start.split(":"))
    end_h, end_m = map(int, work_end.split(":"))
    doctor = Doctor(
        full_name="Dr. Ada Odhiambo",
        specialization="General Practice",
        work_start=time(start_h, start_m),
        work_end=time(end_h, end_m),
    )
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return doctor


def make_patient(db, email="patient@example.com"):
    patient = Patient(full_name="Jane Mwangi", email=email, phone="+254700000001")
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


class TestBookAppointment:
    def test_book_valid_slot(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)
        slot = _future_slot(hours_ahead=3, minute=0)
        # Ensure slot is within working hours (09:00–17:00 UTC)
        slot = slot.replace(hour=10, minute=0)
        if slot <= datetime.now(tz=timezone.utc) + timedelta(hours=1):
            slot = slot + timedelta(days=1)

        appt = booking.book_appointment(db_session, doctor.id, patient.id, slot)
        db_session.commit()

        assert appt.id is not None
        assert appt.status == AppointmentStatus.booked
        assert appt.doctor_id == doctor.id
        assert appt.patient_id == patient.id

    def test_cannot_double_book_same_slot(self, db_session):
        doctor = make_doctor(db_session)
        patient1 = make_patient(db_session, email="p1@example.com")
        patient2 = make_patient(db_session, email="p2@example.com")
        slot = datetime.now(tz=timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

        booking.book_appointment(db_session, doctor.id, patient1.id, slot)
        db_session.commit()

        with pytest.raises(SlotUnavailableError):
            booking.book_appointment(db_session, doctor.id, patient2.id, slot)

    def test_cannot_book_slot_in_past(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)
        past_slot = datetime.now(tz=timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)

        with pytest.raises(ValidationError, match="past"):
            booking.book_appointment(db_session, doctor.id, patient.id, past_slot)

    def test_cannot_book_within_one_hour_of_now(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)
        # 30 minutes from now, on the hour
        soon = datetime.now(tz=timezone.utc) + timedelta(minutes=30)
        soon = soon.replace(second=0, microsecond=0, minute=0 if soon.minute < 30 else 30)

        with pytest.raises(ValidationError, match="1 hour"):
            booking.book_appointment(db_session, doctor.id, patient.id, soon)

    def test_cannot_book_outside_working_hours(self, db_session):
        doctor = make_doctor(db_session, work_start="09:00", work_end="17:00")
        patient = make_patient(db_session)
        outside_slot = datetime.now(tz=timezone.utc).replace(
            hour=20, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

        with pytest.raises(ValidationError, match="working hours"):
            booking.book_appointment(db_session, doctor.id, patient.id, outside_slot)

    def test_cannot_book_on_non_30_minute_boundary(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)
        bad_slot = datetime.now(tz=timezone.utc).replace(
            hour=10, minute=15, second=0, microsecond=0
        ) + timedelta(days=1)

        with pytest.raises(ValidationError, match="30-minute"):
            booking.book_appointment(db_session, doctor.id, patient.id, bad_slot)

    def test_doctor_not_found(self, db_session):
        patient = make_patient(db_session)
        slot = datetime.now(tz=timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)

        from app.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            booking.book_appointment(db_session, 9999, patient.id, slot)

    def test_patient_not_found(self, db_session):
        doctor = make_doctor(db_session)
        slot = datetime.now(tz=timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)

        from app.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            booking.book_appointment(db_session, doctor.id, 9999, slot)

    def test_different_doctors_can_share_same_slot(self, db_session):
        doctor1 = make_doctor(db_session)
        doctor2 = Doctor(
            full_name="Dr. Brian Otieno",
            specialization="Dentistry",
            work_start=__import__("datetime").time(9, 0),
            work_end=__import__("datetime").time(17, 0),
        )
        db_session.add(doctor2)
        db_session.commit()
        db_session.refresh(doctor2)

        patient1 = make_patient(db_session, email="p1@example.com")
        patient2 = make_patient(db_session, email="p2@example.com")

        slot = datetime.now(tz=timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

        appt1 = booking.book_appointment(db_session, doctor1.id, patient1.id, slot)
        db_session.commit()
        appt2 = booking.book_appointment(db_session, doctor2.id, patient2.id, slot)
        db_session.commit()

        assert appt1.doctor_id != appt2.doctor_id
        assert appt1.slot_time == appt2.slot_time


class TestCancelAppointment:
    def _book(self, db, doctor, patient):
        slot = datetime.now(tz=timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        appt = booking.book_appointment(db, doctor.id, patient.id, slot)
        db.commit()
        return appt

    def test_cancel_happy_path(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)
        appt = self._book(db_session, doctor, patient)

        cancelled = booking.cancel_appointment(db_session, appt.id, "Patient request")
        db_session.commit()

        assert cancelled.status == AppointmentStatus.cancelled
        assert cancelled.cancellation_reason == "Patient request"

    def test_cancel_already_cancelled_raises_conflict(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)
        appt = self._book(db_session, doctor, patient)

        booking.cancel_appointment(db_session, appt.id, "First cancel")
        db_session.commit()

        with pytest.raises(ConflictError):
            booking.cancel_appointment(db_session, appt.id, "Second cancel")

    def test_cancelled_slot_becomes_bookable_again(self, db_session):
        doctor = make_doctor(db_session)
        patient1 = make_patient(db_session, email="p1@example.com")
        patient2 = make_patient(db_session, email="p2@example.com")
        slot = datetime.now(tz=timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

        appt = booking.book_appointment(db_session, doctor.id, patient1.id, slot)
        db_session.commit()
        booking.cancel_appointment(db_session, appt.id, "Changed mind")
        db_session.commit()

        new_appt = booking.book_appointment(db_session, doctor.id, patient2.id, slot)
        db_session.commit()
        assert new_appt.status == AppointmentStatus.booked


class TestRescheduleAppointment:
    def _book(self, db, doctor, patient, hour=10):
        slot = datetime.now(tz=timezone.utc).replace(
            hour=hour, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        appt = booking.book_appointment(db, doctor.id, patient.id, slot)
        db.commit()
        return appt

    def test_reschedule_happy_path(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)
        appt = self._book(db_session, doctor, patient, hour=10)

        new_slot = appt.slot_time + timedelta(hours=2)
        rescheduled = booking.reschedule_appointment(db_session, appt.id, new_slot)
        db_session.commit()

        assert rescheduled.slot_time == new_slot
        assert rescheduled.status == AppointmentStatus.booked

    def test_old_slot_freed_after_reschedule(self, db_session):
        doctor = make_doctor(db_session)
        patient1 = make_patient(db_session, email="p1@example.com")
        patient2 = make_patient(db_session, email="p2@example.com")

        slot1 = datetime.now(tz=timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        slot2 = slot1 + timedelta(hours=2)

        appt = booking.book_appointment(db_session, doctor.id, patient1.id, slot1)
        db_session.commit()
        booking.reschedule_appointment(db_session, appt.id, slot2)
        db_session.commit()

        # slot1 should now be free
        new_appt = booking.book_appointment(db_session, doctor.id, patient2.id, slot1)
        db_session.commit()
        assert new_appt.status == AppointmentStatus.booked

    def test_reschedule_cancelled_raises_conflict(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)
        appt = self._book(db_session, doctor, patient, hour=10)
        booking.cancel_appointment(db_session, appt.id, "cancelled")
        db_session.commit()

        new_slot = appt.slot_time + timedelta(hours=2)
        with pytest.raises(ConflictError):
            booking.reschedule_appointment(db_session, appt.id, new_slot)

    def test_reschedule_to_taken_slot_raises_conflict(self, db_session):
        doctor = make_doctor(db_session)
        patient1 = make_patient(db_session, email="p1@example.com")
        patient2 = make_patient(db_session, email="p2@example.com")

        slot1 = datetime.now(tz=timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        slot2 = slot1 + timedelta(hours=2)

        appt1 = booking.book_appointment(db_session, doctor.id, patient1.id, slot1)
        appt2 = booking.book_appointment(db_session, doctor.id, patient2.id, slot2)
        db_session.commit()

        with pytest.raises(SlotUnavailableError):
            booking.reschedule_appointment(db_session, appt1.id, slot2)

    def test_reschedule_to_same_slot_raises_validation(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)
        appt = self._book(db_session, doctor, patient, hour=10)

        with pytest.raises(ValidationError, match="same"):
            booking.reschedule_appointment(db_session, appt.id, appt.slot_time)


class TestAvailability:
    def test_availability_shows_booked_slot_as_unavailable(self, db_session):
        doctor = make_doctor(db_session, work_start="09:00", work_end="10:00")
        patient = make_patient(db_session)
        tomorrow = (datetime.now(tz=timezone.utc) + timedelta(days=1)).date()
        slot = datetime.combine(tomorrow, __import__("datetime").time(9, 0), tzinfo=timezone.utc)

        booking.book_appointment(db_session, doctor.id, patient.id, slot)
        db_session.commit()

        slots = booking.get_availability(db_session, doctor.id, tomorrow.isoformat())
        booked = [s for s in slots if s["slot_time"] == slot.isoformat()]
        assert len(booked) == 1
        assert booked[0]["available"] is False

    def test_availability_invalid_date_raises_validation(self, db_session):
        doctor = make_doctor(db_session)
        with pytest.raises(ValidationError):
            booking.get_availability(db_session, doctor.id, "not-a-date")


class TestPatientAppointments:
    def test_upcoming_appointments_sorted(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)

        tomorrow = (datetime.now(tz=timezone.utc) + timedelta(days=1)).date()
        slot1 = datetime.combine(tomorrow, __import__("datetime").time(10, 0), tzinfo=timezone.utc)
        slot2 = datetime.combine(tomorrow, __import__("datetime").time(11, 0), tzinfo=timezone.utc)
        slot3 = datetime.combine(tomorrow, __import__("datetime").time(9, 0), tzinfo=timezone.utc)

        booking.book_appointment(db_session, doctor.id, patient.id, slot1)
        db_session.commit()
        booking.book_appointment(db_session, doctor.id, patient.id, slot2)
        db_session.commit()
        booking.book_appointment(db_session, doctor.id, patient.id, slot3)
        db_session.commit()

        appts = booking.get_patient_upcoming_appointments(db_session, patient.id)
        times = [a.slot_time for a in appts]
        assert times == sorted(times)
        assert len(times) == 3

    def test_cancelled_appointments_not_returned(self, db_session):
        doctor = make_doctor(db_session)
        patient = make_patient(db_session)
        tomorrow = (datetime.now(tz=timezone.utc) + timedelta(days=1)).date()
        slot = datetime.combine(tomorrow, __import__("datetime").time(10, 0), tzinfo=timezone.utc)

        appt = booking.book_appointment(db_session, doctor.id, patient.id, slot)
        db_session.commit()
        booking.cancel_appointment(db_session, appt.id, "test")
        db_session.commit()

        appts = booking.get_patient_upcoming_appointments(db_session, patient.id)
        assert len(appts) == 0
