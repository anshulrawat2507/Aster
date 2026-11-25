"""Run with python -m scripts.check_voice [--providers] [--speech]. Never prints secrets."""

import argparse
import asyncio
import sys

import httpx

from app.config import Settings
from app.voice.errors import provider_error_message
from app.voice.manager import dependencies_available


async def check_speech(settings: Settings, voice_id: str | None = None) -> bool:
    """Generate one short greeting to check real TTS access; consumes speech quota."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.elevenlabs.io/v1/text-to-speech/" + (voice_id or settings.elevenlabs_voice_id),
                headers={"xi-api-key": settings.elevenlabs_api_key.get_secret_value()},
                json={"text": "Hello.", "model_id": settings.elevenlabs_tts_model},
            )
        if response.status_code == 200 and response.content and response.headers.get("content-type", "").startswith("audio/"):
            print(f"ElevenLabs speech: generated {len(response.content)} audio bytes. Voice access confirmed.")
            return True
        print(f"ElevenLabs speech: failed (HTTP {response.status_code})")
        print(provider_error_message("tts", response.text))
    except httpx.HTTPError:
        print("ElevenLabs speech: network request failed; check your connection.")
    return False


async def check_providers(settings: Settings) -> bool:
    checks = [
        ("ElevenLabs voice", "https://api.elevenlabs.io/v1/voices/" + settings.elevenlabs_voice_id,
         {"xi-api-key": settings.elevenlabs_api_key.get_secret_value()}),
        ("Gemini model", "https://generativelanguage.googleapis.com/v1beta/models/" + settings.gemini_model,
         {"x-goog-api-key": settings.google_api_key.get_secret_value()}),
    ]
    passed = True
    async with httpx.AsyncClient(timeout=20) as client:
        for label, url, headers in checks:
            try:
                response = await client.get(url, headers=headers)
                good = response.status_code == 200
                print(f"{label}: {'accessible' if good else 'check account access'} (HTTP {response.status_code})")
                if not good:
                    # Classify internally; never print arbitrary provider payloads.
                    provider = "voice_lookup" if label == "ElevenLabs voice" else "llm"
                    print(provider_error_message(provider, response.text))
                passed = passed and good
            except httpx.HTTPError:
                print(f"{label}: network request failed; check your connection.")
                passed = False
    print("These read-only checks do not prove speech or generation quota. A real call is still required.")
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", action="store_true", help="Make read-only provider requests using .env credentials.")
    parser.add_argument("--speech", action="store_true", help="Generate a short Hello sample to verify TTS access; uses a small amount of speech quota.")
    parser.add_argument("--voice-id", help="Voice ID to test with --speech without changing .env.")
    args = parser.parse_args()
    settings = Settings()
    installed = dependencies_available()
    print(f"Voice dependencies: {'installed' if installed else 'missing; run setup-voice.cmd'}")
    if installed:
        try:
            from app.voice.runtime import VoiceSession  # noqa: F401
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            SileroVADAnalyzer()
            print("Pipecat imports and Silero model: OK")
        except Exception as error:
            print(f"Pipecat runtime could not load ({type(error).__name__}). Reinstall voice dependencies.")
            return 1
    fields = {
        "ELEVENLABS_API_KEY": bool(settings.elevenlabs_api_key.get_secret_value()),
        "ELEVENLABS_VOICE_ID": bool(settings.elevenlabs_voice_id),
        "GOOGLE_API_KEY": bool(settings.google_api_key.get_secret_value()),
    }
    for name, present in fields.items():
        print(f"{name}: {'set' if present else 'missing'}")
    print(f"Gemini model: {settings.gemini_model}")
    if args.speech:
        if not fields["ELEVENLABS_API_KEY"] or not (args.voice_id or settings.elevenlabs_voice_id):
            print("Speech check requires an ElevenLabs key and voice ID.")
            return 1
        if not asyncio.run(check_speech(settings, args.voice_id)):
            return 1
    if args.providers:
        if not all(fields.values()):
            print("Provider checks skipped until all credentials are set.")
            return 1
        if not asyncio.run(check_providers(settings)):
            return 1
    return 0 if installed else 1


if __name__ == "__main__":
    sys.exit(main())
