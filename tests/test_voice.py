import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.services import AppointmentError, AppointmentService
from app.voice.confirmation import PhoneConfirmation, phone_candidates
from app.voice.manager import VoiceManager, VoiceOffer, dependencies_available
from app.voice.tools import CallTools

PHONE = "+919876543210"


def confirm(confirmation):
    confirmation.observe_user("My number is 98765 43210")
    prompt = confirmation.request(PHONE)
    confirmation.started_speaking()
    confirmation.observe_assistant(prompt["say_exactly"])
    confirmation.stopped_speaking()
    confirmation.observe_user("Yes, that's correct.")


class ConfirmationTests(unittest.TestCase):
    def test_digits_and_spelled_digits_are_recognized(self):
        for text in ["98765 43210", "nine eight seven six five four three two one zero", "plus nine one nine eight seven six five four three two one zero"]:
            with self.subTest(text=text):
                self.assertIn(PHONE, phone_candidates(text))

    def test_unheard_number_cannot_be_read_back(self):
        state = PhoneConfirmation()
        state.observe_user("I need an appointment")
        with self.assertRaises(AppointmentError) as error:
            state.request(PHONE)
        self.assertEqual(error.exception.code, "phone_not_heard")

    def test_success_requires_actual_readback_and_later_yes(self):
        state = PhoneConfirmation()
        confirm(state)
        self.assertEqual(state.require_confirmed(), PHONE)

    def test_yes_before_readback_does_not_confirm(self):
        state = PhoneConfirmation()
        state.observe_user("9876543210")
        state.request(PHONE)
        state.observe_user("yes")
        with self.assertRaises(AppointmentError):
            state.require_confirmed()

    def test_readback_without_finished_audio_does_not_confirm(self):
        state = PhoneConfirmation()
        state.observe_user("9876543210")
        result = state.request(PHONE)
        state.started_speaking()
        state.observe_assistant(result["say_exactly"])
        state.observe_user("yes")
        self.assertIsNone(state.confirmed_phone)

    def test_wrong_readback_does_not_confirm(self):
        state = PhoneConfirmation()
        state.observe_user("9876543210")
        state.request(PHONE)
        state.observe_assistant("I heard plus nine one nine eight seven six five four three two one one. Is that correct?")
        state.stopped_speaking()
        state.observe_user("yes")
        self.assertIsNone(state.confirmed_phone)

    def test_interrupted_readback_must_be_repeated(self):
        state = PhoneConfirmation()
        state.observe_user("9876543210")
        prompt = state.request(PHONE)
        state.started_speaking()
        state.observe_assistant(prompt["say_exactly"])
        state.interrupt()
        state.stopped_speaking()
        state.observe_user("yes")
        self.assertIsNone(state.confirmed_phone)

    def test_ambiguous_agreement_and_negation_are_not_confirmation(self):
        for reply in ["maybe", "yes but no", "not correct", "no", "book tomorrow"]:
            with self.subTest(reply=reply):
                state = PhoneConfirmation()
                state.observe_user("9876543210")
                prompt = state.request(PHONE)
                state.observe_assistant(prompt["say_exactly"])
                state.stopped_speaking()
                state.observe_user(reply)
                self.assertIsNone(state.confirmed_phone)

    def test_phone_correction_invalidates_confirmation(self):
        state = PhoneConfirmation()
        confirm(state)
        state.observe_user("Actually use 9123456789")
        self.assertIsNone(state.confirmed_phone)
        self.assertIsNone(state.pending_phone)

    def test_word_by_word_tts_readback_is_accepted(self):
        state = PhoneConfirmation()
        state.observe_user("9876543210")
        prompt = state.request(PHONE)
        for word in prompt["say_exactly"].split():
            state.observe_assistant(word)
        state.stopped_speaking()
        state.observe_user("yes")
        self.assertEqual(state.require_confirmed(), PHONE)

    def test_confirmation_is_not_shared_between_calls(self):
        first, second = PhoneConfirmation(), PhoneConfirmation()
        confirm(first)
        second.observe_user("yes")
        with self.assertRaises(AppointmentError):
            second.require_confirmed()


class VoiceToolsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="aster-voice-")
        database = Database(Path(self.directory.name) / "clinic.sqlite3")
        database.initialize()
        self.now = datetime(2026, 11, 24, 3, 0, tzinfo=timezone.utc)
        self.service = AppointmentService(database, ZoneInfo("Asia/Kolkata"), lambda: self.now)
        self.confirmation = PhoneConfirmation()
        self.tools = CallTools(self.service, self.confirmation)
        self.slot = self.tools.execute("check_doctor_availability", {"doctor_id": "meera-shah", "day": "2026-11-25"})["slots"][0]

    def tearDown(self):
        self.directory.cleanup()

    def test_spoken_booking_and_cancellation_in_one_session(self):
        confirm(self.confirmation)
        result = self.tools.execute("book_appointment", {"slot_id": self.slot["id"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "booked")
        self.assertIsNone(self.confirmation.confirmed_phone)
        # A new action needs another readback, even when the number is unchanged.
        self.assertEqual(self.tools.execute("cancel_appointment", {})["code"], "phone_confirmation_required")
        confirm(self.confirmation)
        cancelled = self.tools.execute("cancel_appointment", {})
        self.assertTrue(cancelled["ok"])
        self.assertEqual(cancelled["action"], "cancelled")

    def test_model_cannot_supply_confirmation_boolean_or_phone(self):
        result = self.tools.execute("book_appointment", {"slot_id": self.slot["id"], "phone": PHONE, "phone_confirmed": True})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "phone_confirmation_required")

    def test_only_offered_slots_can_be_booked(self):
        confirm(self.confirmation)
        result = self.tools.execute("book_appointment", {"slot_id": "invented-slot"})
        self.assertEqual(result["code"], "availability_required")

    def test_conflict_returns_tool_error_and_preserves_confirmed_phone(self):
        self.service.book_appointment(self.slot["id"], "9123456789", True)
        confirm(self.confirmation)
        result = self.tools.execute("book_appointment", {"slot_id": self.slot["id"]})
        self.assertEqual(result["code"], "slot_unavailable")
        self.assertEqual(self.confirmation.require_confirmed(), PHONE)

    def test_invalid_arguments_and_unknown_tools_are_recoverable(self):
        self.assertEqual(self.tools.execute("check_doctor_availability", {"day": "tomorrow"})["code"], "invalid_arguments")
        self.assertEqual(self.tools.execute("delete_everything", {})["code"], "unknown_tool")
        self.assertFalse(self.tools.execute("prepare_phone_confirmation", {})["ok"])

    def test_ambiguous_cancellation_does_not_change_any_appointment(self):
        self.service.book_appointment(self.slot["id"], PHONE, True)
        other = self.service.check_doctor_availability("arjun-rao")[0]
        self.service.book_appointment(other["id"], PHONE, True)
        confirm(self.confirmation)
        result = self.tools.execute("cancel_appointment", {})
        self.assertEqual(result["code"], "appointment_selection_required")
        self.assertTrue(all(row["status"] == "booked" for row in self.service.list_appointments()))
        selected = result["details"]["appointments"][0]["id"]
        self.assertTrue(self.tools.execute("cancel_appointment", {"appointment_id": selected})["ok"])


class FakeSession:
    def __init__(self):
        self.done = asyncio.Event()
        self.stopped = False
        self.messages = []

    def answer(self):
        return {"sdp": "test-answer", "type": "answer", "pc_id": "test-peer"}

    async def run(self):
        await self.done.wait()

    async def stop(self):
        self.stopped = True
        self.done.set()

    def send(self, message):
        self.messages.append(message)


class VoiceManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = Settings(_env_file=None, elevenlabs_api_key="fake-eleven-secret", elevenlabs_voice_id="test-voice", google_api_key="fake-google-secret", voice_max_sessions=1)
        self.created = []

        async def factory(settings, service, offer):
            session = FakeSession()
            self.created.append(session)
            return session

        self.manager = VoiceManager(self.settings, None, factory=factory)
        self.offer = VoiceOffer(type="offer", sdp="test-sdp-offer")
        self.patch = patch("app.voice.manager.dependencies_available", return_value=True)
        self.patch.start()

    async def asyncTearDown(self):
        await self.manager.shutdown()
        self.patch.stop()

    async def test_start_and_end_cleanup(self):
        answer = await self.manager.offer(self.offer)
        self.assertIn(answer["call_id"], self.manager.calls)
        await self.manager.end(answer["call_id"])
        self.assertEqual(self.manager.calls, {})
        self.assertTrue(self.created[0].stopped)
        await self.manager.end(answer["call_id"])  # Hang-up is idempotent.

    async def test_capacity_limit(self):
        await self.manager.offer(self.offer)
        with self.assertRaises(AppointmentError) as error:
            await self.manager.offer(self.offer)
        self.assertEqual(error.exception.status, 429)

    async def test_missing_dependencies_do_not_start_provider_calls(self):
        with patch("app.voice.manager.dependencies_available", return_value=False):
            with self.assertRaises(AppointmentError) as error:
                await self.manager.offer(self.offer)
        self.assertEqual(error.exception.status, 503)
        self.assertEqual(self.created, [])

    async def test_status_never_returns_credentials(self):
        text = str(self.manager.status())
        self.assertNotIn("fake-eleven-secret", text)
        self.assertNotIn("fake-google-secret", text)
        self.assertNotIn("test-voice", text)
        self.assertFalse(self.manager.status()["provider_access_verified"])

    async def test_missing_key_is_reported_by_name_only(self):
        settings = Settings(_env_file=None, elevenlabs_api_key="dummy", elevenlabs_voice_id="voice", google_api_key="")
        manager = VoiceManager(settings, None)
        self.assertEqual(manager.status()["missing_settings"], ["GOOGLE_API_KEY"])
        self.assertFalse(manager.status()["ready"])

    async def test_factory_error_does_not_leak_secret(self):
        async def broken(*args):
            raise RuntimeError("fake-google-secret")
        self.manager.factory = broken
        with self.assertRaises(AppointmentError) as error:
            await self.manager.offer(self.offer)
        self.assertNotIn("fake-google-secret", str(error.exception))
        self.assertEqual(self.manager.calls, {})


class VoiceRouteTests(unittest.TestCase):
    def test_voice_unavailable_keeps_dashboard_working_and_rejects_browser_identity(self):
        with tempfile.TemporaryDirectory(prefix="aster-routes-") as directory:
            settings = Settings(_env_file=None, database_path=Path(directory) / "test.sqlite3", google_api_key="", elevenlabs_api_key="", elevenlabs_voice_id="")
            with TestClient(create_app(settings)) as client:
                self.assertEqual(client.get("/api/dashboard").status_code, 200)
                self.assertFalse(client.get("/api/voice/status").json()["ready"])
                self.assertEqual(client.post("/api/voice/offer", json={"sdp": "test-sdp-offer", "type": "offer"}).status_code, 503)
                self.assertEqual(client.post("/api/voice/offer", json={"sdp": "test-sdp-offer", "type": "offer", "phone": PHONE}).status_code, 422)
                self.assertEqual(client.post("/api/voice/calls/not-found/end").status_code, 200)
                for path in ["/static/voice.js", "/static/voice.css"]:
                    self.assertEqual(client.get(path).status_code, 200)

    @unittest.skipUnless(dependencies_available(), "Pipecat packages have not been installed")
    def test_pipecat_runtime_imports_and_silero_model_loads(self):
        from app.voice.runtime import VoiceSession
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        self.assertTrue(callable(VoiceSession))
        self.assertIsNotNone(SileroVADAnalyzer())


if __name__ == "__main__":
    unittest.main()
