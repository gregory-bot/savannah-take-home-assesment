from pydantic import BaseModel, ConfigDict, EmailStr


class PatientBase(BaseModel):
    full_name: str
    email: EmailStr
    phone: str | None = None


class PatientCreate(PatientBase):
    pass


class PatientResponse(PatientBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
