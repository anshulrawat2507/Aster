import unittest

from app.voice.errors import provider_error_message
from app.voice.manager import dependencies_available


class ProviderErrorTests(unittest.TestCase):
    def test_invalid_voice_gives_the_setting_to_fix(self):
        message = provider_error_message("tts", "received 1008: A voice with voice_id private-id does not exist.")
        self.assertIn("ELEVENLABS_VOICE_ID", message)
        self.assertNotIn("private-id", message)

    def test_metadata_permission_does_not_claim_speech_access_failed(self):
        message = provider_error_message("voice_lookup", "missing_permissions: missing the permission voices_read")
        self.assertIn("Voices: Read", message)
        self.assertIn("separately", message)

    def test_payment_restriction_does_not_claim_the_key_is_invalid(self):
        message = provider_error_message("tts", "payment_required: Free users cannot use library voices via the API")
        self.assertIn("free plan", message)
        self.assertIn("current plan", message)
        self.assertNotIn("rejected the API key", message)

    def test_creator_only_voice_reports_the_plan_restriction(self):
        message = provider_error_message("tts", "free_users_not_allowed: You need to be on the creator tier or above to use this voice.")
        self.assertIn("Creator tier or above", message)
        self.assertNotIn("API key", message)

    def test_errors_never_echo_provider_payloads(self):
        for detail in ("invalid_api_key", "quota_exceeded", "missing_permissions", "unknown failure"):
            with self.subTest(detail=detail):
                message = provider_error_message("stt", detail + " secret-value https://private.example")
                self.assertNotIn("secret-value", message)
                self.assertNotIn("private.example", message)
                self.assertIn("ElevenLabs speech recognition", message)

    @unittest.skipUnless(dependencies_available(), "Pipecat packages have not been installed")
    def test_original_error_survives_later_no_audio_failure(self):
        from app.voice.runtime import VoiceSession
        session = VoiceSession.__new__(VoiceSession)
        session.error_reported = False
        messages = []
        session.send = messages.append
        session.report_provider_error("tts", "A voice with voice_id invalid does not exist.")
        session.report_provider_error("tts", "TTS context completed with no audio")
        self.assertEqual(len(messages), 1)
        self.assertIn("ELEVENLABS_VOICE_ID", messages[0]["message"])


if __name__ == "__main__":
    unittest.main()
