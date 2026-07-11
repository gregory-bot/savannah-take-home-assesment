"""
HTTP-level integration tests using FastAPI TestClient.
"""

from datetime import datetime, timedelta, timezone


def _tomorrow_slot(hour: int = 10, minute: int = 0) -> str:
    slot = (datetime.now(tz=timezone.utc) + timedelta(days=1)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return slot.isoformat()


def create_doctor(client, work_start="09:00", work_end="17:00"):
    resp = client.post("/api/doctors", json={
        "full_name": "Dr. Ada Odhiambo",
        "specialization": "General Practice",
        "work_start": work_start,
        "work_end": work_end,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_patient(client, email="patient@example.com"):
    resp = client.post("/api/patients", json={
        "full_name": "Jane Mwangi",
        "email": email,
        "phone": "+254700000001",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestDoctorsEndpoints:
    def test_create_and_list_doctors(self, client):
        create_doctor(client)
        resp = client.get("/api/doctors")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_doctor_not_found(self, client):
        resp = client.get("/api/doctors/9999")
        assert resp.status_code == 404

    def test_get_availability(self, client):
        doctor = create_doctor(client)
        tomorrow = (datetime.now(tz=timezone.utc) + timedelta(days=1)).date().isoformat()
        resp = client.get(f"/api/doctors/{doctor['id']}/availability?date={tomorrow}")
        assert resp.status_code == 200
        slots = resp.json()
        assert len(slots) == 16  # 09:00–17:00 = 8 hours = 16 slots
        assert all("slot_time" in s and "available" in s for s in slots)

    def test_get_availability_invalid_date(self, client):
        doctor = create_doctor(client)
        resp = client.get(f"/api/doctors/{doctor['id']}/availability?date=bad-date")
        assert resp.status_code == 422


class TestAppointmentEndpoints:
    def test_book_appointment(self, client):
        doctor = create_doctor(client)
        patient = create_patient(client)
        resp = client.post("/api/appointments", json={
            "doctor_id": doctor["id"],
            "patient_id": patient["id"],
            "slot_time": _tomorrow_slot(10, 0),
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "booked"
        assert data["doctor"]["id"] == doctor["id"]
        assert data["patient"]["id"] == patient["id"]

    def test_double_booking_returns_409(self, client):
        doctor = create_doctor(client)
        patient1 = create_patient(client, email="p1@example.com")
        patient2 = create_patient(client, email="p2@example.com")
        slot = _tomorrow_slot(10, 0)

        r1 = client.post("/api/appointments", json={
            "doctor_id": doctor["id"], "patient_id": patient1["id"], "slot_time": slot,
        })
        assert r1.status_code == 201

        r2 = client.post("/api/appointments", json={
            "doctor_id": doctor["id"], "patient_id": patient2["id"], "slot_time": slot,
        })
        assert r2.status_code == 409

    def test_book_outside_working_hours_returns_422(self, client):
        doctor = create_doctor(client)
        patient = create_patient(client)
        resp = client.post("/api/appointments", json={
            "doctor_id": doctor["id"],
            "patient_id": patient["id"],
            "slot_time": _tomorrow_slot(20, 0),
        })
        assert resp.status_code == 422

    def test_cancel_appointment(self, client):
        doctor = create_doctor(client)
        patient = create_patient(client)
        appt = client.post("/api/appointments", json={
            "doctor_id": doctor["id"],
            "patient_id": patient["id"],
            "slot_time": _tomorrow_slot(10, 0),
        }).json()

        resp = client.patch(f"/api/appointments/{appt['id']}/cancel", json={"reason": "Busy"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        assert resp.json()["cancellation_reason"] == "Busy"

    def test_cancel_already_cancelled_returns_409(self, client):
        doctor = create_doctor(client)
        patient = create_patient(client)
        appt = client.post("/api/appointments", json={
            "doctor_id": doctor["id"],
            "patient_id": patient["id"],
            "slot_time": _tomorrow_slot(10, 0),
        }).json()

        client.patch(f"/api/appointments/{appt['id']}/cancel", json={"reason": "First"})
        resp = client.patch(f"/api/appointments/{appt['id']}/cancel", json={"reason": "Second"})
        assert resp.status_code == 409

    def test_reschedule_appointment(self, client):
        doctor = create_doctor(client)
        patient = create_patient(client)
        appt = client.post("/api/appointments", json={
            "doctor_id": doctor["id"],
            "patient_id": patient["id"],
            "slot_time": _tomorrow_slot(10, 0),
        }).json()

        resp = client.patch(f"/api/appointments/{appt['id']}/reschedule", json={
            "new_slot_time": _tomorrow_slot(11, 0),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "11:00" in data["slot_time"]

    def test_reschedule_cancelled_returns_409(self, client):
        doctor = create_doctor(client)
        patient = create_patient(client)
        appt = client.post("/api/appointments", json={
            "doctor_id": doctor["id"],
            "patient_id": patient["id"],
            "slot_time": _tomorrow_slot(10, 0),
        }).json()

        client.patch(f"/api/appointments/{appt['id']}/cancel", json={"reason": "test"})
        resp = client.patch(f"/api/appointments/{appt['id']}/reschedule", json={
            "new_slot_time": _tomorrow_slot(11, 0),
        })
        assert resp.status_code == 409


class TestPatientEndpoints:
    def test_patient_upcoming_appointments(self, client):
        doctor = create_doctor(client)
        patient = create_patient(client)

        client.post("/api/appointments", json={
            "doctor_id": doctor["id"],
            "patient_id": patient["id"],
            "slot_time": _tomorrow_slot(10, 0),
        })
        client.post("/api/appointments", json={
            "doctor_id": doctor["id"],
            "patient_id": patient["id"],
            "slot_time": _tomorrow_slot(11, 0),
        })

        resp = client.get(f"/api/patients/{patient['id']}/appointments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        times = [d["slot_time"] for d in data]
        assert times == sorted(times)

    def test_duplicate_patient_email_returns_409(self, client):
        create_patient(client, email="same@example.com")
        resp = client.post("/api/patients", json={
            "full_name": "Other Person",
            "email": "same@example.com",
        })
        assert resp.status_code == 409


class TestHealthCheck:
    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"