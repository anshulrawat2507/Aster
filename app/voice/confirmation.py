"""Phone confirmation based on speech frames, never an LLM-supplied boolean.

This module deliberately has no Pipecat dependency, so its rules can be tested
without a microphone, network, or provider account.
"""

import re
from dataclasses import dataclass, field

from app.models import normalize_phone
from app.services import AppointmentError

DIGITS = {word: str(number) for number, word in enumerate(
    ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
)}
DIGITS.update({"oh": "0", "o": "0"})
AFFIRMATIVE = re.compile(r"^(yes|yeah|yep|correct|right|that is correct|that's correct|that is right|that's right|yes that is correct|yes that's correct|yes correct|yes please|confirmed|i confirm)[.! ,]*$", re.I)


def phone_candidates(text: str) -> set[str]:
    """Recognize digit sequences and individually spoken English digits.

    Ambiguous grouped words such as 'ninety eight' are deliberately not guessed.
    The agent can ask the caller to repeat the number one digit at a time.
    """
    tokens = re.findall(r"\+|[0-9]+|[a-z]+", text.lower())
    candidates, sequence = set(), ""

    def finish():
        if sequence:
            try:
                candidates.add(normalize_phone(sequence))
            except ValueError:
                pass

    for token in tokens + ["STOP"]:
        if token.isascii() and token.isdigit():
            sequence += token
        elif token in DIGITS:
            sequence += DIGITS[token]
        elif token in ("+", "plus") and not sequence:
            sequence = "+"
        else:
            finish()
            sequence = ""
    return candidates


def spoken_phone(phone: str) -> str:
    words = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
    return "plus " + ", ".join(words[int(digit)] for digit in phone.lstrip("+"))


@dataclass
class PhoneConfirmation:
    heard_phones: set[str] = field(default_factory=set)
    pending_phone: str | None = None
    confirmed_phone: str | None = None
    readback_complete: bool = False
    readback_text: str = ""
    user_turn: int = 0
    requested_turn: int = -1
    bot_speaking: bool = False

    def observe_user(self, text: str):
        self.user_turn += 1
        numbers = phone_candidates(text)
        self.heard_phones.update(numbers)
        # A correction containing a different phone always invalidates old consent.
        if numbers and (self.pending_phone or self.confirmed_phone) not in numbers:
            self.clear_confirmation()
        if not self.pending_phone or self.user_turn <= self.requested_turn:
            return
        reply = " ".join(re.sub(r"[^a-z' ]", " ", text.lower().replace("\u2019", "'")).split())
        if self.readback_complete and not self.bot_speaking and AFFIRMATIVE.fullmatch(reply):
            self.confirmed_phone = self.pending_phone
            self.pending_phone = None
        elif re.search(r"\b(no|nope|wrong|incorrect|change|instead)\b", text, re.I):
            self.clear_confirmation()

    def request(self, phone: str) -> dict:
        if not isinstance(phone, str):
            raise AppointmentError("invalid_phone", "Provide the spoken phone as text.", 422)
        try:
            normalized = normalize_phone(phone)
        except ValueError as error:
            raise AppointmentError("invalid_phone", str(error), 422) from error
        if normalized not in self.heard_phones:
            raise AppointmentError(
                "phone_not_heard", "Ask the caller to say the phone number, one digit at a time. Do not infer it.", 422,
            )
        self.clear_confirmation()
        self.pending_phone = normalized
        self.requested_turn = self.user_turn
        return {
            "status": "awaiting_spoken_confirmation",
            "say_exactly": f"I heard {spoken_phone(normalized)}. Is that correct? Please say yes or no.",
            "instruction": "Read the supplied sentence aloud and WAIT for the next caller response. Do not book or cancel yet.",
        }

    def observe_assistant(self, text: str):
        if self.pending_phone and not self.readback_complete:
            self.readback_text = (self.readback_text + " " + text)[-1500:]

    def started_speaking(self):
        self.bot_speaking = True

    def stopped_speaking(self):
        self.bot_speaking = False
        if self.pending_phone:
            self.readback_complete = (
                self.pending_phone in phone_candidates(self.readback_text)
                and bool(re.search(r"\b(correct|right)\b", self.readback_text, re.I))
            )

    def interrupt(self):
        # A reply after completed readback is allowed; a cut-off readback is not.
        if self.pending_phone and not self.readback_complete:
            self.readback_text = ""

    def require_confirmed(self) -> str:
        if not self.confirmed_phone:
            raise AppointmentError(
                "phone_confirmation_required",
                "Use prepare_phone_confirmation, read the number aloud completely, then wait for the caller to say yes.",
                422,
            )
        return self.confirmed_phone

    def clear_confirmation(self):
        self.pending_phone = None
        self.confirmed_phone = None
        self.readback_complete = False
        self.readback_text = ""
