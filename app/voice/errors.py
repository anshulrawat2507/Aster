"""Actionable provider errors without exposing provider payloads or credentials."""


def provider_error_message(provider: str, detail: str) -> str:
    text = detail.lower()
    label = {
        "tts": "ElevenLabs text to speech",
        "stt": "ElevenLabs speech recognition",
        "llm": "Gemini",
        "voice_lookup": "ElevenLabs voice lookup",
    }.get(provider, "The voice service")
    if provider == "voice_lookup" and "voices_read" in text:
        return "The ElevenLabs key needs Voices: Read permission for this lookup. Speech access must be checked separately."
    if "free_users_not_allowed" in text:
        if "creator tier" in text:
            return "ElevenLabs requires Creator tier or above for this voice. Choose a voice your current plan allows through the API."
        return "ElevenLabs does not allow this voice on the free plan. Choose a voice your current plan allows through the API."
    if "payment_required" in text or "free users cannot use library voices" in text:
        return "ElevenLabs does not allow this library voice through the API on the free plan. Choose a voice your current plan allows through the API, or change your ElevenLabs plan."
    if provider in {"tts", "voice_lookup"} and (
        "voice_not_found" in text or ("voice" in text and "does not exist" in text)
    ):
        return "ElevenLabs cannot use the selected voice. Check ELEVENLABS_VOICE_ID in .env and your plan's API access for that voice, then restart the app. Library voices are unavailable through the API on the free plan."
    if "missing_permissions" in text or "missing the permission" in text:
        return f"{label} is not permitted by this API key. Enable the required permission in the provider account, then try again."
    if any(term in text for term in ("quota", "resource_exhausted", "insufficient_credits", "rate_limit", "rate limit")):
        return f"{label} reached an account quota or rate limit. Check available credits and limits before trying again."
    if any(term in text for term in ("invalid_api_key", "api_key_invalid", "api key not valid", "unauthenticated")):
        return f"{label} rejected the API key. Update the key in .env and restart the app."
    if provider == "tts" and "no audio" in text:
        return "ElevenLabs returned no speech. Check the selected voice, Text to Speech permission, and available credits."
    return f"{label} could not respond. Check its settings, account access, and connection, then try again."
