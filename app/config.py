from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_path: Path = ROOT / "data" / "clinic.sqlite3"
    clinic_timezone: str = "Asia/Kolkata"
    elevenlabs_api_key: SecretStr = SecretStr("")
    elevenlabs_voice_id: str = ""
    google_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    elevenlabs_stt_model: str = "scribe_v2_realtime"
    elevenlabs_tts_model: str = "eleven_flash_v2_5"
    voice_max_call_seconds: int = Field(default=600, ge=30, le=1800)
    voice_max_sessions: int = Field(default=2, ge=1, le=5)

    @field_validator("gemini_model", mode="before")
    @classmethod
    def default_gemini_model(cls, value):
        return value.strip() if isinstance(value, str) and value.strip() else "gemini-3.5-flash-lite"

    @field_validator("elevenlabs_api_key", "google_api_key", mode="before")
    @classmethod
    def strip_secret(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("elevenlabs_voice_id", mode="before")
    @classmethod
    def strip_voice_id(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("database_path")
    @classmethod
    def absolute_database_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else ROOT / value

    @field_validator("clinic_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value
