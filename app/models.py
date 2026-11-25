import re

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


def normalize_phone(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"\+?[0-9 ().-]+", value):
        raise ValueError("Use digits and an optional country code, for example +91 98765 43210.")
    digits = re.sub(r"[^0-9]", "", value)
    if not value.startswith("+"):
        if len(digits) == 10:
            digits = "91" + digits
        elif not (len(digits) == 12 and digits.startswith("91")):
            raise ValueError("Use a 10-digit Indian number or include + and the country code.")
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        raise ValueError("Enter a valid phone number with its country code.")
    return "+" + digits


class PhoneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=8, max_length=32, examples=["+91 98765 43210"])
    phone_confirmed: StrictBool = Field(
        description="True only after the agent reads the number back and the caller confirms it."
    )

    @field_validator("phone")
    @classmethod
    def normalized_phone(cls, value: str) -> str:
        return normalize_phone(value)


class BookingRequest(PhoneRequest):
    slot_id: str = Field(min_length=1, max_length=100)


class CancellationRequest(PhoneRequest):
    appointment_id: str | None = Field(default=None, min_length=1, max_length=100)
