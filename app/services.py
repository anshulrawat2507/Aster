import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.db import Database
from app.models import normalize_phone


class AppointmentError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details=None):
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        super().__init__(message)


APPOINTMENT_QUERY = """
SELECT a.*, s.starts_at, s.ends_at, s.doctor_id,
       d.name AS doctor_name, d.specialty
FROM appointments a
JOIN slots s ON s.id = a.slot_id
JOIN doctors d ON d.id = s.doctor_id
"""


def public_appointment(row) -> dict:
    result = dict(row)
    phone = result.pop("phone")
    result["phone_masked"] = "+" + "\u2022" * (len(phone) - 5) + phone[-4:]
    return result


class AppointmentService:
    """Shared business rules for HTTP and the future Pipecat function handlers."""

    def __init__(self, database: Database, zone: ZoneInfo, clock: Callable[[], datetime] | None = None):
        self.database = database
        self.zone = zone
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def dates(self) -> list[str]:
        today = self.clock().astimezone(self.zone).date()
        return [(today + timedelta(days=offset)).isoformat() for offset in range(8)]

    def list_doctors(self) -> list[dict]:
        with self.database.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM doctors ORDER BY rowid")]

    def check_doctor_availability(self, doctor_id: str | None = None, day: date | None = None) -> list[dict]:
        now = self.clock()
        self.database.seed_slots(now, self.zone)
        clauses = ["s.starts_at > ?", "NOT EXISTS (SELECT 1 FROM appointments a WHERE a.slot_id = s.id AND a.status = 'booked')"]
        values = [now.astimezone(timezone.utc).isoformat()]
        with self.database.connect() as connection:
            if doctor_id:
                if not connection.execute("SELECT 1 FROM doctors WHERE id = ?", (doctor_id,)).fetchone():
                    raise AppointmentError("doctor_not_found", "That doctor could not be found.", 404)
                clauses.append("s.doctor_id = ?")
                values.append(doctor_id)
            if day:
                start = datetime.combine(day, time.min, self.zone).astimezone(timezone.utc)
                end = datetime.combine(day + timedelta(days=1), time.min, self.zone).astimezone(timezone.utc)
                clauses.extend(["s.starts_at >= ?", "s.starts_at < ?"])
                values.extend([start.isoformat(), end.isoformat()])
            query = """SELECT s.*, d.name AS doctor_name, d.specialty FROM slots s
                       JOIN doctors d ON d.id = s.doctor_id WHERE """ + " AND ".join(clauses) + " ORDER BY s.starts_at, d.name"
            return [dict(row) for row in connection.execute(query, values)]

    @staticmethod
    def confirmed_phone(phone: str, phone_confirmed: bool) -> str:
        if phone_confirmed is not True:
            raise AppointmentError("phone_confirmation_required", "Read the phone number back and get confirmation first.", 422)
        try:
            return normalize_phone(phone)
        except ValueError as error:
            raise AppointmentError("invalid_phone", str(error), 422) from error

    def book_appointment(self, slot_id: str, phone: str, phone_confirmed: bool) -> dict:
        phone = self.confirmed_phone(phone, phone_confirmed)
        with self.database.connect() as connection:
            # Serialize the check and write. The unique index also protects every writer.
            connection.execute("BEGIN IMMEDIATE")
            slot = connection.execute("SELECT * FROM slots WHERE id = ?", (slot_id,)).fetchone()
            if not slot:
                raise AppointmentError("slot_not_found", "That slot could not be found. Check availability again.", 404)
            if datetime.fromisoformat(slot["starts_at"]) <= self.clock():
                raise AppointmentError("slot_in_past", "That appointment time has passed. Choose another slot.", 409)
            appointment_id = "apt_" + uuid4().hex[:16]
            try:
                connection.execute(
                    "INSERT INTO appointments (id, slot_id, phone, status, created_at) VALUES (?, ?, ?, 'booked', ?)",
                    (appointment_id, slot_id, phone, self.clock().astimezone(timezone.utc).isoformat()),
                )
            except sqlite3.IntegrityError as error:
                raise AppointmentError("slot_unavailable", "That slot has just been booked. Please choose another.", 409) from error
            return public_appointment(connection.execute(APPOINTMENT_QUERY + " WHERE a.id = ?", (appointment_id,)).fetchone())

    def cancel_appointment(self, phone: str, phone_confirmed: bool, appointment_id: str | None = None) -> dict:
        phone = self.confirmed_phone(phone, phone_confirmed)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            query = APPOINTMENT_QUERY + " WHERE a.phone = ? AND a.status = 'booked' AND s.starts_at > ?"
            values = [phone, self.clock().astimezone(timezone.utc).isoformat()]
            if appointment_id:
                query += " AND a.id = ?"
                values.append(appointment_id)
            matches = connection.execute(query + " ORDER BY s.starts_at", values).fetchall()
            if not matches:
                raise AppointmentError("appointment_not_found", "No upcoming booking was found for that phone number.", 404)
            if len(matches) > 1:
                raise AppointmentError(
                    "appointment_selection_required", "There is more than one booking. Ask which appointment to cancel.",
                    409, {"appointments": [public_appointment(row) for row in matches]},
                )
            selected_id = matches[0]["id"]
            connection.execute(
                "UPDATE appointments SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
                (self.clock().astimezone(timezone.utc).isoformat(), selected_id),
            )
            return public_appointment(connection.execute(APPOINTMENT_QUERY + " WHERE a.id = ?", (selected_id,)).fetchone())

    def list_appointments(self) -> list[dict]:
        with self.database.connect() as connection:
            return [public_appointment(row) for row in connection.execute(APPOINTMENT_QUERY + " ORDER BY s.starts_at, a.created_at")]
