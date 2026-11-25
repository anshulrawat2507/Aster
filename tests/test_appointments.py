import tempfile
import re
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services import AppointmentError


class AppointmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="aster-tests-")
        self.settings = Settings(database_path=Path(self.directory.name) / "test.sqlite3", clinic_timezone="Asia/Kolkata", _env_file=None)
        self.app = create_app(self.settings)
        self.service = self.app.state.service
        self.now = datetime(2026, 11, 24, 3, 0, tzinfo=timezone.utc)
        self.service.clock = lambda: self.now
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.slot = self.client.get("/api/availability", params={"doctor_id": "meera-shah", "day": "2026-11-25"}).json()["slots"][0]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def book(self, **overrides):
        body = {"slot_id": self.slot["id"], "phone": "9876543210", "phone_confirmed": True}
        body.update(overrides)
        return self.client.post("/api/appointments", json=body)

    def cancel(self, **overrides):
        body = {"phone": "+91 98765 43210", "phone_confirmed": True}
        body.update(overrides)
        return self.client.post("/api/appointments/cancel", json=body)

    def test_dashboard_is_seeded_without_fake_bookings(self):
        data = self.client.get("/api/dashboard").json()
        self.assertEqual(len(data["doctors"]), 4)
        self.assertEqual(len(data["dates"]), 8)
        self.assertEqual(len(data["slots"]), 24)
        self.assertEqual(data["appointments"], [])
        self.assertFalse(data["voice"]["ready"])
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")

    def test_booking_updates_availability_and_masks_phone(self):
        response = self.book()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "booked")
        self.assertNotIn("phone", response.json())
        self.assertTrue(response.json()["phone_masked"].endswith("3210"))
        data = self.client.get("/api/dashboard", params={"day": "2026-11-25"}).json()
        self.assertNotIn(self.slot["id"], [slot["id"] for slot in data["slots"]])
        self.assertEqual(len(data["appointments"]), 1)
        self.assertNotIn("9876543210", str(data))

    def test_double_booking_is_rejected(self):
        self.book()
        response = self.book(phone="9123456789")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "slot_unavailable")
        self.assertEqual(len(self.service.list_appointments()), 1)

    def test_concurrent_booking_only_one_wins(self):
        def attempt(phone):
            try:
                self.service.book_appointment(self.slot["id"], phone, True)
                return "booked"
            except AppointmentError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, ["9876543210", "9123456789"]))
        self.assertCountEqual(outcomes, ["booked", "slot_unavailable"])

    def test_cancel_by_phone_releases_slot_and_retains_history(self):
        self.book()
        response = self.cancel()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertIsNotNone(response.json()["cancelled_at"])
        available = self.client.get("/api/availability").json()["slots"]
        self.assertIn(self.slot["id"], [slot["id"] for slot in available])
        self.assertEqual(self.book().status_code, 201)
        self.assertEqual(len(self.service.list_appointments()), 2)

    def test_cancellation_does_not_use_only_appointment_id(self):
        appointment = self.book().json()
        response = self.cancel(phone="9123456789", appointment_id=appointment["id"])
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.service.list_appointments()[0]["status"], "booked")

    def test_multiple_bookings_require_selection(self):
        first = self.book().json()
        slots = self.client.get("/api/availability", params={"doctor_id": "arjun-rao", "day": "2026-11-25"}).json()["slots"]
        self.book(slot_id=slots[0]["id"])
        response = self.cancel()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "appointment_selection_required")
        self.assertEqual(len(response.json()["error"]["details"]["appointments"]), 2)
        self.assertTrue(all(item["status"] == "booked" for item in self.service.list_appointments()))
        self.assertEqual(self.cancel(appointment_id=first["id"]).status_code, 200)
        self.assertEqual(sum(item["status"] == "booked" for item in self.service.list_appointments()), 1)

    def test_confirmation_is_required_and_strict(self):
        for value in [False, "true", 1, None]:
            with self.subTest(value=value):
                self.assertEqual(self.book(phone_confirmed=value).status_code, 422)
        self.assertEqual(self.client.post("/api/appointments", json={"slot_id": self.slot["id"], "phone": "9876543210"}).status_code, 422)
        self.book()
        self.assertEqual(self.cancel(phone_confirmed=False).status_code, 422)
        self.assertEqual(self.service.list_appointments()[0]["status"], "booked")

    def test_service_also_requires_confirmation(self):
        with self.assertRaises(AppointmentError) as error:
            self.service.book_appointment(self.slot["id"], "9876543210", False)
        self.assertEqual(error.exception.code, "phone_confirmation_required")

    def test_phone_validation(self):
        for phone in ["hello1234567890", "123", "+000000000000", "+1234567890123456", "12+34567890", "+９８７６５４３２１０"]:
            with self.subTest(phone=phone):
                self.assertEqual(self.book(phone=phone).status_code, 422)

    def test_international_phone_is_supported(self):
        self.assertEqual(self.book(phone="+1 (415) 555-0123").status_code, 201)
        self.assertEqual(self.cancel(phone="+14155550123").status_code, 200)

    def test_unknown_slot_and_doctor(self):
        self.assertEqual(self.book(slot_id="does-not-exist").status_code, 404)
        self.assertEqual(self.client.get("/api/availability", params={"doctor_id": "does-not-exist"}).status_code, 404)
        self.assertEqual(self.cancel().status_code, 404)

    def test_past_slots_cannot_be_booked_or_offered(self):
        self.now = datetime.fromisoformat(self.slot["starts_at"]) + timedelta(minutes=1)
        response = self.book()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "slot_in_past")
        slots = self.client.get("/api/availability").json()["slots"]
        self.assertTrue(all(datetime.fromisoformat(slot["starts_at"]) > self.now for slot in slots))

    def test_past_appointments_cannot_be_cancelled(self):
        self.book()
        self.now = datetime.fromisoformat(self.slot["starts_at"]) + timedelta(hours=1)
        self.assertEqual(self.cancel().status_code, 404)

    def test_dates_use_clinic_timezone_and_reject_invalid_input(self):
        self.now = datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc)
        data = self.client.get("/api/dashboard").json()
        self.assertEqual(data["selected_date"], "2026-11-25")
        self.assertEqual(data["dates"][0], "2026-11-25")
        self.assertEqual(self.client.get("/api/availability?day=not-a-date").status_code, 422)
        self.assertEqual(self.client.get("/api/availability?day=2020-01-01").json()["slots"], [])

    def test_restart_preserves_bookings_and_does_not_duplicate_slots(self):
        appointment = self.book().json()
        restarted = create_app(self.settings)
        restarted.state.service.clock = lambda: self.now
        with TestClient(restarted) as client:
            data = client.get("/api/dashboard", params={"day": "2026-11-25"}).json()
            self.assertEqual(len(data["slots"]), 23)
            self.assertEqual(data["appointments"][0]["id"], appointment["id"])

    def test_dashboard_assets_and_api_docs_are_served(self):
        for route in ["/", "/static/styles.css", "/static/dashboard.js", "/static/favicon.svg", "/docs", "/openapi.json"]:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 200)
        self.assertEqual(self.client.get("/api/appointments").headers["cache-control"], "no-store")

    def test_page_and_voice_assets_cannot_mix_cached_versions(self):
        page = self.client.get("/")
        self.assertEqual(page.headers['cache-control'], 'no-store')
        for filename in ('voice.js', 'voice.css'):
            match = re.search(r'/static/' + re.escape(filename) + r'\?v=[0-9a-f]{12}', page.text)
            self.assertIsNotNone(match)
            asset = self.client.get(match.group())
            self.assertEqual(asset.status_code, 200)
            self.assertEqual(asset.headers['cache-control'], 'no-cache')


if __name__ == "__main__":
    unittest.main()
