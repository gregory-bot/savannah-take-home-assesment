from datetime import time

from sqlalchemy import String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    specialization: Mapped[str] = mapped_column(String(100), nullable=False)
    work_start: Mapped[time] = mapped_column(Time, nullable=False)
    work_end: Mapped[time] = mapped_column(Time, nullable=False)

    appointments: Mapped[list["Appointment"]] = relationship(  # noqa: F821
        "Appointment", back_populates="doctor"
    )
