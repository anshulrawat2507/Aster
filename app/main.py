from contextlib import asynccontextmanager
from datetime import date
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.db import Database
from app.models import BookingRequest, CancellationRequest
from app.services import AppointmentError, AppointmentService
from app.voice.manager import VoiceManager, VoiceOffer

STATIC = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = Database(settings.database_path)
    service = AppointmentService(database, ZoneInfo(settings.clinic_timezone))
    voice = VoiceManager(settings, service)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        database.seed_slots(service.clock(), service.zone)
        try:
            yield
        finally:
            await voice.shutdown()

    application = FastAPI(
        title="Aster Clinic API", version="0.3.0", lifespan=lifespan,
        description="Local appointment backend with an optional Pipecat voice agent.",
    )
    application.state.service = service
    application.state.voice = voice

    @application.exception_handler(AppointmentError)
    async def appointment_error_handler(request, error: AppointmentError):
        return JSONResponse(status_code=error.status, content={
            "error": {"code": error.code, "message": error.message, "details": error.details}
        })

    @application.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path == "/" or request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @application.get("/api/health", tags=["System"])
    def health():
        with database.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "phase": 3, "timezone": settings.clinic_timezone, "voice_ready": voice.status()["ready"]}

    @application.get("/api/dashboard", tags=["Dashboard"])
    def dashboard(day: date | None = Query(default=None)):
        selected_day = day or service.clock().astimezone(service.zone).date()
        return {
            "timezone": settings.clinic_timezone,
            "selected_date": selected_day.isoformat(),
            "dates": service.dates(),
            "doctors": service.list_doctors(),
            "slots": service.check_doctor_availability(day=selected_day),
            "appointments": service.list_appointments(),
            "voice": voice.status(),
        }

    @application.get("/api/doctors", tags=["Doctors"])
    def doctors():
        return {"doctors": service.list_doctors()}

    @application.get("/api/availability", tags=["Appointments"])
    def availability(doctor_id: str | None = None, day: date | None = None):
        return {"slots": service.check_doctor_availability(doctor_id, day), "timezone": settings.clinic_timezone}

    @application.get("/api/appointments", tags=["Appointments"])
    def appointments():
        return {"appointments": service.list_appointments()}

    @application.post("/api/appointments", status_code=201, tags=["Appointments"])
    def book_appointment(body: BookingRequest):
        return service.book_appointment(**body.model_dump())

    @application.post("/api/appointments/cancel", tags=["Appointments"])
    def cancel_appointment(body: CancellationRequest):
        return service.cancel_appointment(**body.model_dump())

    @application.get("/api/voice/status", tags=["Voice"])
    def voice_status():
        return voice.status()

    @application.post("/api/voice/offer", tags=["Voice"])
    async def voice_offer(body: VoiceOffer):
        return await voice.offer(body)

    @application.get("/api/voice/calls/{call_id}/input", tags=["Voice"])
    def voice_input_status(call_id: str):
        return voice.input_diagnostics(call_id)

    @application.post("/api/voice/calls/{call_id}/end", tags=["Voice"])
    async def end_call(call_id: str):
        await voice.end(call_id)
        return {"status": "ended"}

    @application.get("/", include_in_schema=False)
    def index():
        # Changed script/style content gets a new URL, including for browsers
        # that still have an older unversioned asset in their cache.
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for filename in ("styles.css", "voice.css", "call-experience.js", "voice.js", "dashboard.js"):
            version = sha256((STATIC / filename).read_bytes()).hexdigest()[:12]
            html = html.replace(f'"/static/{filename}"', f'"/static/{filename}?v={version}"')
        return HTMLResponse(html)

    application.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")
    return application


app = create_app()
