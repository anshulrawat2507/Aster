import sqlite3
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DOCTORS = [
    ("meera-shah", "Dr. Meera Shah", "General physician", "MS", "teal", "Everyday health & preventive care"),
    ("arjun-rao", "Dr. Arjun Rao", "Cardiologist", "AR", "blue", "Heart health & cardiovascular care"),
    ("ananya-iyer", "Dr. Ananya Iyer", "Dermatologist", "AI", "rose", "Skin, hair & personalised care"),
    ("kabir-sen", "Dr. Kabir Sen", "Paediatrician", "KS", "amber", "Thoughtful care for little ones"),
]
SLOT_TIMES = [time(9, 0), time(9, 30), time(10, 30), time(11, 0), time(14, 0), time(15, 30)]

SCHEMA = """
CREATE TABLE IF NOT EXISTS doctors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    specialty TEXT NOT NULL,
    initials TEXT NOT NULL,
    color TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS slots (
    id TEXT PRIMARY KEY,
    doctor_id TEXT NOT NULL REFERENCES doctors(id),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    UNIQUE(doctor_id, starts_at)
);
CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY,
    slot_id TEXT NOT NULL REFERENCES slots(id),
    phone TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('booked', 'cancelled')),
    created_at TEXT NOT NULL,
    cancelled_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_booking_per_slot
    ON appointments(slot_id) WHERE status = 'booked';
CREATE INDEX IF NOT EXISTS appointments_by_phone ON appointments(phone, status);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            connection.executemany("INSERT OR IGNORE INTO doctors VALUES (?, ?, ?, ?, ?, ?)", DOCTORS)

    def seed_slots(self, now: datetime, zone: ZoneInfo):
        """Maintain a rolling 8-day demo schedule without touching existing bookings."""
        first_day = now.astimezone(zone).date()
        rows = []
        for offset in range(8):
            day = first_day + timedelta(days=offset)
            for doctor in DOCTORS:
                for slot_time in SLOT_TIMES:
                    start = datetime.combine(day, slot_time, zone).astimezone(timezone.utc)
                    slot_id = f"{doctor[0]}_{day.isoformat()}_{slot_time:%H%M}"
                    rows.append((slot_id, doctor[0], start.isoformat(), (start + timedelta(minutes=30)).isoformat()))
        with self.connect() as connection:
            connection.executemany("INSERT OR IGNORE INTO slots VALUES (?, ?, ?, ?)", rows)
