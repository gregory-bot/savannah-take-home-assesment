from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.patient import Patient
from app.schemas.appointment import AppointmentResponse
from app.schemas.patient import PatientCreate, PatientResponse
from app.services import booking

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.post("", response_model=PatientResponse, status_code=201)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    """Register a new patient."""
    from sqlalchemy import select
    existing = db.scalars(select(Patient).where(Patient.email == payload.email)).first()
    if existing:
        from app.exceptions import ConflictError
        raise ConflictError(f"A patient with email '{payload.email}' already exists.")

    patient = Patient(**payload.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.get("", response_model=list[PatientResponse])
def list_patients(db: Session = Depends(get_db)):
    """List all patients."""
    return db.query(Patient).all()


@router.get("/{patient_id}", response_model=PatientResponse)
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    """Get a single patient by ID."""
    return booking.get_patient_or_404(db, patient_id)


@router.get("/{patient_id}/appointments", response_model=list[AppointmentResponse])
def get_patient_appointments(patient_id: int, db: Session = Depends(get_db)):
    """Return upcoming (booked, not cancelled) appointments for a patient, sorted by date."""
    return booking.get_patient_upcoming_appointments(db, patient_id)
