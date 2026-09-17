from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from .config import Settings
from .database import create_database_engine, create_schema, create_session_factory
from .repository import CycleNotFound, FeedbackConflict, GarmentAlreadyExists, Repository
from .schemas import (
    DebugIngestRequest,
    DisplaySnapshot,
    GarmentRegistrationRequest,
    HealthResponse,
    InspectionRequest,
    InspectionResponse,
)
from .service import StationService

logger = logging.getLogger(__name__)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str, json_logs: bool) -> None:
    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(app_settings.log_level, app_settings.json_logs)
        engine = create_database_engine(app_settings.database_url)
        if app_settings.auto_create_schema:
            create_schema(engine)
        factory = create_session_factory(engine)
        repository = Repository(factory, app_settings)
        if app_settings.seed_mock_data:
            repository.seed_mock_data()
        service = StationService(app_settings, repository)
        app.state.engine = engine
        app.state.service = service
        await service.start()
        try:
            yield
        finally:
            await service.stop()
            engine.dispose()

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    def service(request: Request) -> StationService:
        return request.app.state.service

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        current = service(request).broker.current
        health_state = current.health
        healthy = (
            health_state.backend_ok
            and health_state.database_ok
            and health_state.serial_connected
            and health_state.serial_fresh
            and health_state.rfid_ok
            and health_state.scale_ok
        )
        return HealthResponse(
            status="ok" if healthy else "degraded",
            version=app_settings.app_version,
            health=health_state,
        )

    @app.get("/api/v1/state", response_model=DisplaySnapshot)
    async def state(request: Request) -> DisplaySnapshot:
        return service(request).broker.current

    @app.get("/api/v1/events", response_class=StreamingResponse)
    async def events(
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            revision = int(last_event_id) if last_event_id is not None else -1
        except ValueError:
            revision = -1
        broker = service(request).broker

        async def stream() -> AsyncIterator[str]:
            nonlocal revision
            while not await request.is_disconnected():
                snapshot = await broker.wait_after(revision, timeout_s=15.0)
                if snapshot is None:
                    yield ": keepalive\n\n"
                    continue
                revision = snapshot.revision
                yield (
                    f"id: {snapshot.revision}\nevent: state\ndata: {snapshot.model_dump_json()}\n\n"
                )

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post(
        "/api/v1/cycles/{cycle_id}/inspection",
        response_model=InspectionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def inspection(
        cycle_id: str, payload: InspectionRequest, request: Request
    ) -> InspectionResponse:
        try:
            return await service(request).add_feedback(cycle_id, payload)
        except CycleNotFound as exc:
            raise HTTPException(status_code=404, detail="cycle not found") from exc
        except FeedbackConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/cycles/{cycle_id}/garment", response_model=DisplaySnapshot)
    async def register_garment(
        cycle_id: str, payload: GarmentRegistrationRequest, request: Request
    ) -> DisplaySnapshot:
        try:
            return await service(request).resolve_new_garment(cycle_id, payload)
        except CycleNotFound as exc:
            raise HTTPException(status_code=404, detail="no garment awaiting registration") from exc
        except GarmentAlreadyExists as exc:
            raise HTTPException(status_code=409, detail="garment already registered") from exc

    @app.post("/api/v1/debug/reports", response_model=DisplaySnapshot)
    async def debug_report(payload: DebugIngestRequest, request: Request) -> DisplaySnapshot:
        try:
            return await service(request).debug_ingest(payload.message)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

    return app


app = create_app()
