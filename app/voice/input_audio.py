"""Ephemeral microphone diagnostics: levels and counters, never recorded audio."""

from array import array
import math
import sys
import time


class InputAudioStats:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.frames = self.signal_frames = 0
        self.partial_transcripts = self.final_transcripts = 0
        self.last_audio_at = None
        self.last_report_at = float('-inf')
        self.peak_rms = 0.0

    def observe(self, audio: bytes) -> dict | None:
        if not audio:
            return None
        samples = array('h')
        samples.frombytes(audio[:len(audio) - len(audio) % 2])
        if not samples:
            return None
        if sys.byteorder != 'little':
            samples.byteswap()
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
        now = self.clock()
        self.frames += 1
        self.signal_frames += int(rms >= 0.001)
        self.peak_rms = max(self.peak_rms, rms)
        self.last_audio_at = now
        if now - self.last_report_at < 0.25:
            return None
        self.last_report_at = now
        # Map -70..0 dBFS onto the meter; this is a sound level, not a speech score.
        level = max(0.0, min(1.0, (20 * math.log10(max(rms, 1e-8)) + 70) / 70))
        return {"type": "input_audio", "level": round(level, 3), "has_sound": rms >= 0.001}

    def snapshot(self) -> dict:
        return {
            "audio_frames": self.frames,
            "frames_with_sound": self.signal_frames,
            "peak_rms": round(self.peak_rms, 5),
            "last_audio_seconds_ago": None if self.last_audio_at is None else round(self.clock() - self.last_audio_at, 2),
            "partial_transcripts": self.partial_transcripts,
            "final_transcripts": self.final_transcripts,
        }
