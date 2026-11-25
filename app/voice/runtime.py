"""Real Pipecat runtime. Imported only when a configured voice call starts.

Audio: browser -> SmallWebRTC -> ElevenLabs STT -> Gemini/tool calls ->
ElevenLabs TTS -> SmallWebRTC -> browser. No browser speech APIs or fake audio.
"""

import asyncio
import sys
from contextlib import suppress

from loguru import logger
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    BotStartedSpeakingFrame, BotStoppedSpeakingFrame, FunctionCallResultProperties,
    InputAudioRawFrame, InterimTranscriptionFrame, InterruptionFrame, TTSSpeakFrame, TTSTextFrame, TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.elevenlabs.stt import CommitStrategy, ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from app.voice.confirmation import PhoneConfirmation
from app.voice.errors import provider_error_message
from app.voice.input_audio import InputAudioStats
from app.voice.tools import CallTools, TOOL_DEFINITIONS, system_prompt


def configure_logging(settings):
    secrets = [settings.elevenlabs_api_key.get_secret_value(), settings.google_api_key.get_secret_value()]

    def redact(record):
        for secret in secrets:
            if secret:
                record["message"] = record["message"].replace(secret, "[redacted]")
        return True

    # Pipecat's DEBUG output includes conversation text. Keep local default logs quiet.
    logger.remove()
    logger.add(sys.stderr, level="WARNING", filter=redact, backtrace=False, diagnose=False)


class MicrophoneMonitor(FrameProcessor):
    def __init__(self, session):
        super().__init__()
        self.session = session

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, InputAudioRawFrame):
            update = self.session.input_stats.observe(frame.audio)
            if update is not None:
                self.session.send(update)
        await self.push_frame(frame, direction)


class CallerMonitor(FrameProcessor):
    def __init__(self, session):
        super().__init__()
        self.session = session

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, InterimTranscriptionFrame):
                self.session.input_stats.partial_transcripts += 1
                self.session.send({"type": "transcript", "role": "user", "text": frame.text, "final": False})
            elif isinstance(frame, TranscriptionFrame):
                self.session.input_stats.final_transcripts += 1
                self.session.confirmation.observe_user(frame.text)
                self.session.send({"type": "transcript", "role": "user", "text": frame.text, "final": True})
        await self.push_frame(frame, direction)


class PlaybackMonitor(FrameProcessor):
    """Observe delivered TTS text and playback boundaries after the output transport."""

    def __init__(self, session):
        super().__init__()
        self.session = session

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, TTSTextFrame):
                self.session.confirmation.observe_assistant(frame.text)
                self.session.send({"type": "assistant_text", "text": frame.text})
            elif isinstance(frame, BotStartedSpeakingFrame):
                self.session.confirmation.started_speaking()
                self.session.send({"type": "speaking", "speaking": True})
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self.session.confirmation.stopped_speaking()
                self.session.send({"type": "speaking", "speaking": False})
            elif isinstance(frame, InterruptionFrame):
                self.session.confirmation.interrupt()
                self.session.send({"type": "interrupted"})
        await self.push_frame(frame, direction)


class VoiceSession:
    def __init__(self, settings, service, connection):
        self.connection = connection
        self.confirmation = PhoneConfirmation()
        self.input_stats = InputAudioStats()
        self.tools = CallTools(service, self.confirmation)
        self.stopped = False
        self.error_reported = False
        self.runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
        self.transport = SmallWebRTCTransport(
            webrtc_connection=connection,
            params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
        )
        self.stt = ElevenLabsRealtimeSTTService(
            api_key=settings.elevenlabs_api_key.get_secret_value(),
            commit_strategy=CommitStrategy.MANUAL,
            settings=ElevenLabsRealtimeSTTService.Settings(model=settings.elevenlabs_stt_model, language=Language.EN),
            enable_logging=False,
        )
        self.tts = ElevenLabsTTSService(
            api_key=settings.elevenlabs_api_key.get_secret_value(),
            # Calls already end on provider errors. Report the original websocket
            # rejection before a reconnect turns it into a generic no-audio error.
            reconnect_on_error=False,
            settings=ElevenLabsTTSService.Settings(
                model=settings.elevenlabs_tts_model, voice=settings.elevenlabs_voice_id,
                language=Language.EN, stability=0.6, similarity_boost=0.75,
            ),
        )
        self.llm = GoogleLLMService(
            api_key=settings.google_api_key.get_secret_value(),
            settings=GoogleLLMService.Settings(
                model=settings.gemini_model, system_instruction=system_prompt(service),
                temperature=0.3,
            ),
        )
        schemas = []
        for definition in TOOL_DEFINITIONS:
            schemas.append(FunctionSchema(**definition))
            self.llm.register_function(definition["name"], self.handle_tool)
        context = LLMContext(tools=ToolsSchema(standard_tools=schemas))
        user, assistant = LLMContextAggregatorPair(
            context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
        )
        self.worker = PipelineWorker(
            Pipeline([
                self.transport.input(), MicrophoneMonitor(self), self.stt, CallerMonitor(self), user,
                self.llm, self.tts, self.transport.output(), PlaybackMonitor(self), assistant,
            ]),
            params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000),
            idle_timeout_secs=120,
            enable_rtvi=False,  # Native browser WebRTC; our small data-channel event protocol.
            processor_unusable_policy=ProcessorUnusablePolicy.END,
        )

        @self.transport.event_handler("on_client_connected")
        async def connected(transport, client):
            self.send({"type": "call_ready"})
            await self.worker.queue_frames([TTSSpeakFrame("Hello, I'm Aster. I can help you find a doctor, book a visit, or cancel an appointment. What would you like to do?")])

        @self.transport.event_handler("on_client_disconnected")
        async def disconnected(transport, client):
            await self.runner.cancel()

        @self.transport.event_handler("on_app_message")
        async def app_message(transport, message, client):
            # Never accept a phone or confirmation from browser messages.
            if isinstance(message, dict) and message.get("type") == "end_call":
                await self.runner.cancel()

        @self.worker.event_handler("on_pipeline_error")
        async def pipeline_error(worker, frame):
            provider = "tts" if frame.processor is self.tts else "stt" if frame.processor is self.stt else "llm" if frame.processor is self.llm else "unknown"
            self.report_provider_error(provider, frame.error)
            await self.runner.cancel()

        @self.tts.event_handler("on_connection_error")
        async def tts_connection_error(tts, error):
            self.report_provider_error("tts", error)

        @self.worker.event_handler("on_idle_timeout")
        async def idle(worker):
            self.send({"type": "call_ended", "message": "The call ended after two minutes of inactivity."})

    async def handle_tool(self, params: FunctionCallParams):
        # Keep confirmation decisions and the database action in a single event-loop turn.
        # SQLite statements are short; conflicting writes are also protected by its unique index.
        result = self.tools.execute(params.function_name, params.arguments)
        if params.function_name == "prepare_phone_confirmation" and result.get("ok"):
            await params.result_callback(result, properties=FunctionCallResultProperties(run_llm=False))
            # A deterministic spoken readback prevents dropped/reordered digits by the LLM.
            await self.tts.queue_frame(TTSSpeakFrame(result["say_exactly"]))
            return
        await params.result_callback(result)
        if result.get("ok") and result.get("action"):
            self.send({"type": "appointment_updated", "action": result["action"], "appointment": result["appointment"]})

    def report_provider_error(self, provider, detail):
        if not self.error_reported:
            self.error_reported = True
            self.send({"type": "error", "message": provider_error_message(provider, detail)})

    def send(self, message):
        if not self.stopped:
            self.connection.send_app_message(message)

    def answer(self):
        return self.connection.get_answer()

    async def run(self):
        await self.runner.add_workers(self.worker)
        await self.runner.run()

    async def stop(self):
        if self.stopped:
            return
        self.stopped = True
        self.confirmation.clear_confirmation()
        await self.runner.cancel()
        await self.connection.disconnect()


async def create_session(settings, service, offer):
    configure_logging(settings)
    # No external media provider or STUN server is needed for same-machine localhost.
    connection = SmallWebRTCConnection(ice_servers=[], connection_timeout_secs=25)
    try:
        await connection.initialize(sdp=offer.sdp, type=offer.type)
        return VoiceSession(settings, service, connection)
    except BaseException:
        with suppress(Exception):
            await connection.disconnect()
        raise
