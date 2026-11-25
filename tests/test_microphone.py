from array import array
from types import SimpleNamespace
import unittest

from app.config import Settings
from app.services import AppointmentError
from app.voice.input_audio import InputAudioStats
from app.voice.manager import VoiceManager


class MicrophoneInputTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.stats = InputAudioStats(clock=lambda: self.now)

    def test_silence_is_distinguished_from_no_audio(self):
        self.assertIsNone(self.stats.snapshot()['last_audio_seconds_ago'])
        event = self.stats.observe(bytes(640))
        self.assertFalse(event['has_sound'])
        self.assertEqual(event['level'], 0)
        self.assertEqual(self.stats.snapshot()['audio_frames'], 1)
        self.assertEqual(self.stats.snapshot()['last_audio_seconds_ago'], 0)

    def test_quiet_signal_is_visible_and_events_are_throttled(self):
        pcm = array('h', [100, -100] * 160).tobytes()
        event = self.stats.observe(pcm)
        self.assertTrue(event['has_sound'])
        self.assertGreater(event['level'], 0)
        self.now = 0.02
        self.assertIsNone(self.stats.observe(pcm))
        self.now = 0.3
        self.assertIsNotNone(self.stats.observe(pcm))
        self.assertEqual(self.stats.snapshot()['frames_with_sound'], 3)

    def test_snapshot_contains_counts_without_audio_or_transcript_content(self):
        self.stats.observe(array('h', [32767, -32768] * 160).tobytes())
        self.stats.final_transcripts = 1
        self.now = 2
        snapshot = self.stats.snapshot()
        self.assertEqual(snapshot['final_transcripts'], 1)
        self.assertEqual(snapshot['last_audio_seconds_ago'], 2)
        self.assertTrue(all(value is None or isinstance(value, (int, float)) for value in snapshot.values()))
        self.assertLessEqual(self.stats.peak_rms, 1)

    def test_empty_audio_does_not_claim_microphone_is_receiving(self):
        self.assertIsNone(self.stats.observe(b''))
        self.assertIsNone(self.stats.observe(b'\0'))
        self.assertEqual(self.stats.snapshot()['audio_frames'], 0)

    def test_call_diagnostics_are_call_local_and_expire_on_hangup(self):
        manager = VoiceManager(Settings(_env_file=None), None)
        manager.calls['test-call'] = SimpleNamespace(session=SimpleNamespace(input_stats=self.stats))
        self.stats.observe(bytes(640))
        self.assertEqual(manager.input_diagnostics('test-call')['audio_frames'], 1)
        del manager.calls['test-call']
        with self.assertRaises(AppointmentError) as error:
            manager.input_diagnostics('test-call')
        self.assertEqual(error.exception.status, 404)


if __name__ == '__main__':
    unittest.main()
