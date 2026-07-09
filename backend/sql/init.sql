-- ============================================================
-- HealthLink Clinic Booking System — PostgreSQL Schema
-- ============================================================
-- Run this script once against your PostgreSQL database to
-- create all tables, constraints, and indexes.
-- SQLAlchemy will also auto-create these on startup via
-- Base.metadata.create_all(), so this file is provided for
-- reference, manual inspection, or running outside of the app.
-- ============================================================

-- Doctors --------------------------------------------------------
CREATE TABLE IF NOT EXISTS doctors (
    id            SERIAL PRIMARY KEY,
    full_name     VARCHAR(100) NOT NULL,
    specialization VARCHAR(100) NOT NULL,
    work_start    TIME         NOT NULL,
    work_end      TIME         NOT NULL,
    CONSTRAINT chk_work_hours CHECK (work_start < work_end)
);

-- Patients -------------------------------------------------------
CREATE TABLE IF NOT EXISTS patients (
    id        SERIAL PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email     VARCHAR(255) NOT NULL UNIQUE,
    phone     VARCHAR(20)
);

CREATE INDEX IF NOT EXISTS idx_patients_email ON patients (email);

-- Appointments ---------------------------------------------------
CREATE TYPE appointment_status AS ENUM ('booked', 'cancelled');

CREATE TABLE IF NOT EXISTS appointments (
    id                  SERIAL PRIMARY KEY,
    doctor_id           INTEGER      NOT NULL REFERENCES doctors(id)  ON DELETE CASCADE,
    patient_id          INTEGER      NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    slot_time           TIMESTAMPTZ  NOT NULL,
    status              appointment_status NOT NULL DEFAULT 'booked',
    cancellation_reason VARCHAR(500),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- This UNIQUE constraint is the final concurrency guard:
    -- even if two transactions slip past the application-level check,
    -- the database will reject the second INSERT.
    CONSTRAINT uq_doctor_slot UNIQUE (doctor_id, slot_time)
);

CREATE INDEX IF NOT EXISTS idx_appointments_doctor_slot
    ON appointments (doctor_id, slot_time);

CREATE INDEX IF NOT EXISTS idx_appointments_patient_status
    ON appointments (patient_id, status);

-- ============================================================
-- Sample seed data (optional — remove in production)
-- ============================================================

INSERT INTO doctors (full_name, specialization, work_start, work_end) VALUES
    ('Dr. Ada Odhiambo',   'General Practice', '08:00', '16:00'),
    ('Dr. Brian Otieno',   'Cardiology',        '09:00', '17:00'),
    ('Dr. Carol Wanjiku',  'Pediatrics',        '08:00', '14:00'),
    ('Dr. David Kimani',   'Dermatology',       '10:00', '18:00'),
    ('Dr. Eva Muthoni',    'Obstetrics',        '07:00', '15:00')
ON CONFLICT DO NOTHING;

INSERT INTO patients (full_name, email, phone) VALUES
    ('Jane Mwangi',    'jane.mwangi@example.com',    '+254700000001'),
    ('Peter Njoroge',  'peter.njoroge@example.com',  '+254700000002'),
    ('Alice Achieng',  'alice.achieng@example.com',  '+254700000003')
ON CONFLICT DO NOTHING;
