import asyncio
import importlib.util
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.services import AppointmentError, AppointmentService

logger = logging.getLogger(__name__)


class VoiceOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sdp: str = Field(min_length=10, max_length=200_000)
    type: Literal["offer"]


def dependencies_available() -> bool:
    try:
        return all(importlib.util.find_spec(name) is not None for name in (
            "pipecat", "aiortc", "onnxruntime", "google.genai", "websockets",
        ))
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


@dataclass
class ActiveCall:
    session: object
    task: asyncio.Task


class VoiceManager:
    def __init__(self, settings: Settings, service: AppointmentService, factory=None):
        self.settings = settings
        self.service = service
        self.factory = factory
        self.calls: dict[str, ActiveCall] = {}
        self.start_lock = asyncio.Lock()
        self.runtime_failed = False

    def status(self) -> dict:
        credentials = {
            "ELEVENLABS_API_KEY": bool(self.settings.elevenlabs_api_key.get_secret_value()),
            "ELEVENLABS_VOICE_ID": bool(self.settings.elevenlabs_voice_id),
            "GOOGLE_API_KEY": bool(self.settings.google_api_key.get_secret_value()),
        }
        installed = dependencies_available()
        missing = [name for name, present in credentials.items() if not present]
        ready = installed and not missing and not self.runtime_failed
        status = "ready" if ready else "runtime_error" if self.runtime_failed else "dependencies_missing" if not installed else "credentials_missing"
        return {
            "ready": ready, "status": status, "dependencies_installed": installed,
            "missing_settings": missing, "active_calls": len(self.calls),
            "model": self.settings.gemini_model,
            "provider_access_verified": False,
            "active_inputs": [
                {"call_id": call_id, **call.session.input_stats.snapshot()}
                for call_id, call in self.calls.items()
                if getattr(call.session, "input_stats", None) is not None
            ],
        }

    async def offer(self, offer: VoiceOffer) -> dict:
        status = self.status()
        if not status["ready"]:
            raise AppointmentError(
                "voice_not_ready", "Complete the local voice setup, then restart the server.", 503, status,
            )
        async with self.start_lock:
            if len(self.calls) >= self.settings.voice_max_sessions:
                raise AppointmentError("voice_busy", "All voice sessions are busy. End an existing call and try again.", 429)
            session = None
            try:
                if self.factory is None:
                    # Keep the appointment app runnable before optional voice packages are installed.
                    from app.voice.runtime import create_session
                    self.factory = create_session
                session = await asyncio.wait_for(self.factory(self.settings, self.service, offer), timeout=30)
                call_id = uuid4().hex
                answer = {**session.answer(), "call_id": call_id}
                task = asyncio.create_task(self._run(call_id, session), name=f"voice-{call_id}")
                self.calls[call_id] = ActiveCall(session, task)
                return answer
            except (ImportError, ModuleNotFoundError) as error:
                self.runtime_failed = True
                logger.warning("Voice dependency import failed (%s).", type(error).__name__)
                raise AppointmentError("voice_dependencies_failed", "Voice dependencies could not load. Run setup-voice.cmd and restart.", 503) from None
            except Exception as error:
                if session is not None:
                    with suppress(Exception):
                        await session.stop()
                logger.warning("Voice startup failed (%s).", type(error).__name__)
                raise AppointmentError("voice_start_failed", "Could not start the voice call. Check voice setup and try again.", 503) from None

    async def _run(self, call_id: str, session):
        try:
            await asyncio.wait_for(session.run(), timeout=self.settings.voice_max_call_seconds)
        except TimeoutError:
            session.send({"type": "call_ended", "message": "The call reached its time limit. You can start a new call."})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Voice session failed (%s).", type(error).__name__)
            session.send({"type": "error", "message": "The voice connection failed. Check provider access and try again."})
        finally:
            self.calls.pop(call_id, None)
            with suppress(Exception):
                await session.stop()

    def input_diagnostics(self, call_id: str) -> dict:
        call = self.calls.get(call_id)
        if call is None:
            raise AppointmentError("call_not_found", "This call has ended or does not exist.", 404)
        stats = getattr(call.session, "input_stats", None)
        return stats.snapshot() if stats is not None else {}

    async def end(self, call_id: str):
        call = self.calls.pop(call_id, None)
        if call is None:
            return
        with suppress(Exception):
            await call.session.stop()
        if call.task is not asyncio.current_task() and not call.task.done():
            try:
                await asyncio.wait_for(asyncio.shield(call.task), timeout=5)
            except TimeoutError:
                call.task.cancel()
                with suppress(asyncio.CancelledError):
                    await call.task

    async def shutdown(self):
        await asyncio.gather(*(self.end(call_id) for call_id in list(self.calls)))
