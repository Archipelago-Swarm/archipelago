from __future__ import annotations

import asyncio
import hmac
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from archipelago_contracts.adapter import FixtureAdapter, SimulatorAdapter
from archipelago_contracts.models import Id, Observation, RunConfig, WorldSnapshot
from archipelago_contracts.validate import parse_json
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from .runs import AdapterFactory, Conflict, NotFound, Run, RunManager, Subscriber
from .settings import Settings

COOKIE = "archipelago_session"


def fixture_factory(fixtures: Path) -> AdapterFactory:
    """Fixture-backed adapter until the real T03 adapter is wired in."""

    def make(_: RunConfig) -> SimulatorAdapter:
        obs = parse_json((fixtures / "observation.json").read_text())
        snap = parse_json((fixtures / "world_snapshot.json").read_text())
        assert isinstance(obs, Observation) and isinstance(snap, WorldSnapshot)
        return FixtureAdapter(obs, snap)

    return make


class CommandBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: Id
    command: Literal["pause", "resume", "step", "stop"]
    expected_revision: int


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str


def create_app(settings: Settings, factory: AdapterFactory) -> FastAPI:
    mgr = RunManager(settings, factory)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await mgr.shutdown()

    app = FastAPI(title="Archipelago API", lifespan=lifespan)
    app.state.manager = mgr

    def token_ok(candidate: str | None) -> bool:
        return candidate is not None and hmac.compare_digest(
            candidate.encode(), settings.api_token.encode()
        )

    def bearer(authorization: str | None) -> str | None:
        return authorization.removeprefix("Bearer ") if authorization else None

    def auth(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
        if not (token_ok(bearer(authorization)) or token_ok(request.cookies.get(COOKIE))):
            raise HTTPException(401, "authentication required")

    @app.exception_handler(Conflict)
    async def _conflict(_: Request, e: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.exception_handler(NotFound)
    async def _missing(_: Request, e: NotFound) -> JSONResponse:
        return JSONResponse({"detail": "run not found"}, status_code=404)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        active, store_ok = mgr.active_count(), settings.data_dir.is_dir()
        ready = active < settings.max_active_runs and store_ok
        return JSONResponse(
            {
                "ready": ready,
                "active_runs": active,
                "capacity": settings.max_active_runs,
                "dependencies": {"run_store": "ok" if store_ok else "down"},
            },
            status_code=200 if ready else 503,
        )

    @app.post("/v1/login")
    async def login(body: LoginBody, response: Response) -> dict[str, str]:
        if not token_ok(body.token):
            raise HTTPException(401, "bad token")
        # shortcut: secure=False for local http; set True behind TLS (T10)
        response.set_cookie(COOKIE, body.token, httponly=True, samesite="strict", secure=False)
        return {"status": "ok"}

    @app.post("/v1/runs", dependencies=[Depends(auth)])
    async def create_run(
        config: RunConfig,
        response: Response,
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 128:
            raise HTTPException(400, "Idempotency-Key header required (<=128 chars)")
        run, created = mgr.create(idempotency_key, config)
        response.status_code = 201 if created else 200
        return run.view()

    @app.get("/v1/runs/{run_id}", dependencies=[Depends(auth)])
    async def get_run(run_id: str) -> dict[str, Any]:
        return mgr.get(run_id).view()

    @app.post("/v1/runs/{run_id}/commands", dependencies=[Depends(auth)])
    async def command(run_id: str, body: CommandBody) -> dict[str, Any]:
        return mgr.command(mgr.get(run_id), body.command, body.command_id, body.expected_revision)

    @app.get("/v1/runs/{run_id}/events", dependencies=[Depends(auth)])
    async def events(
        run_id: str,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, Any]:
        run = mgr.get(run_id)
        page = [e for e in run.events if e["sequence"] > after_sequence][:limit]
        return {
            "events": page,
            "oldest_sequence": run.events[0]["sequence"] if run.events else 0,
            "latest_sequence": run.seq,
        }

    async def send(ws: WebSocket, msg: dict[str, Any]) -> None:
        await asyncio.wait_for(ws.send_text(json.dumps(msg)), settings.send_timeout)

    @app.websocket("/v1/runs/{run_id}/stream")
    async def stream(ws: WebSocket, run_id: str) -> None:
        origin = ws.headers.get("origin")
        same = f"{'https' if ws.url.scheme == 'wss' else 'http'}://{ws.headers.get('host')}"
        authed = token_ok(bearer(ws.headers.get("authorization"))) or token_ok(
            ws.cookies.get(COOKIE)
        )
        run: Run | None = mgr.runs.get(run_id)
        bad_origin = (
            origin is not None and origin != same and origin not in settings.allowed_origins
        )
        if bad_origin or not authed or run is None:
            await ws.close(code=1008)
            return
        await ws.accept()
        sub = Subscriber(settings.subscriber_queue)
        run.subs.add(sub)
        try:
            await send(ws, mgr.snapshot_event(run))
            while True:
                ev = await sub.queue.get()
                if sub.lagged:
                    sub.lagged = False
                    await send(ws, {"type": "resnapshot", "reason": "slow_consumer"})
                    await send(ws, mgr.snapshot_event(run))
                    continue
                await send(ws, ev)
        except (WebSocketDisconnect, TimeoutError, RuntimeError):
            pass
        finally:
            run.subs.discard(sub)

    return app


def create_app_from_env() -> FastAPI:
    fixtures = Path(os.environ.get("ARCHIPELAGO_FIXTURE_DIR", "packages/contracts/fixtures/good"))
    return create_app(Settings.from_env(), fixture_factory(fixtures))
