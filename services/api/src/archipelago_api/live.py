"""ARCHIPELAGO_ADAPTER=live: the API as a client of the coordinator.

See live-runtime.md section 9, section 12 and amendments A9 and A11.

The coordinator owns the simulation and the nodes. This module only
- starts a run there from the run config plus a plan NAME resolved from a server-side plan file,
- mirrors status and lifecycle commands (idempotent command ids pass straight through),
- pulls the coordinator's canonical events into the run event log through the same admission
  path as node telemetry, so the stream, replay and the Persister see one stream of records,
- reports readiness from the coordinator and its nodes, independent of run activity.

There is no FixtureAdapter or simulator fallback anywhere on this path.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from archipelago_contracts.models import RunConfig

from .runs import ACTIVE, Conflict, Run, RunManager, Status
from .settings import Settings
from .telemetry import TelemetryIngest

log = logging.getLogger("archipelago.live")
TERMINAL = {"completed", "failed", "interrupted"}
MIN_TOKEN = 16
FORBIDDEN_BODY_KEYS = {"node_urls", "plan_file", "nodes_urls"}


class LiveConfigError(RuntimeError):
    """Live mode was requested but cannot work. Raised at startup; never degrades."""


class UpstreamError(Exception):
    """The coordinator did not answer (connection, timeout, undecodable reply)."""


class Rejected(Exception):
    """The coordinator or the allowlist refused the request (4xx); `status` is relayed."""

    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status, self.detail = status, detail


class CoordinatorClient:
    """Blocking JSON client; the API calls it through asyncio.to_thread."""

    def __init__(self, url: str, token: str, admin_token: str | None, timeout: float) -> None:
        self.url, self.token, self.admin_token, self.timeout = (
            url.rstrip("/"),
            token,
            admin_token,
            timeout,
        )
        # the coordinator is on the private network: never route through an HTTP proxy
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        admin: bool = False,
        timeout: float | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        token = self.admin_token if admin else self.token
        req.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self._opener.open(req, timeout=timeout or self.timeout) as r:
                return r.status, _decode(r.read())
        except urllib.error.HTTPError as e:
            return e.code, _decode(e.read())
        except (OSError, ValueError) as e:  # URLError, timeouts, resets, bad JSON
            raise UpstreamError(type(e).__name__) from None

    def privileged_snapshot(self, run_id: str) -> tuple[int, dict[str, Any]]:
        """Hidden-state snapshot; needs COORDINATOR_ADMIN_TOKEN. Not exposed by any API route."""
        if not self.admin_token:
            raise LiveConfigError("COORDINATOR_ADMIN_TOKEN is not configured")
        return self.request("GET", f"/v1/runs/{run_id}/snapshot", admin=True)


def _decode(raw: bytes) -> dict[str, Any]:
    doc = json.loads(raw or b"{}")
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    return doc


def load_plans(path: Path) -> dict[str, dict[str, Any]]:
    """Server-side plan file: a JSON object mapping plan name -> coordinator Plan."""
    try:  # the coordinator package is a runtime dependency of live mode only
        plan_model: Any = importlib.import_module("archipelago_coordinator.models").Plan
    except ImportError as e:
        raise LiveConfigError(f"archipelago_coordinator package is not importable: {e}") from None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise LiveConfigError(f"COORDINATOR_PLAN_FILE unreadable: {type(e).__name__}") from None
    if not isinstance(doc, dict) or not doc:
        raise LiveConfigError("COORDINATOR_PLAN_FILE must be a JSON object of name -> plan")
    # same shapes as the coordinator's plan file: one Plan, {"plans": {name: Plan}}, or name -> Plan
    if set(doc) == {"plans"} and isinstance(doc["plans"], dict):
        doc = doc["plans"]
    elif "node_urls" in doc:
        doc = {"default": doc}
    plans: dict[str, dict[str, Any]] = {}
    for name, body in doc.items():
        try:
            plans[name] = plan_model.model_validate(body).model_dump(mode="json")
        except ValueError as e:
            raise LiveConfigError(f"plan {name!r} is invalid: {e}") from None
    return plans


def plan_hash(plan: dict[str, Any]) -> str:
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def validate_settings(s: Settings) -> None:
    """Fail visibly at startup when live cannot work."""
    if not s.coordinator_url or urlsplit(s.coordinator_url).scheme not in ("http", "https"):
        raise LiveConfigError("COORDINATOR_URL must be an http(s) URL")
    if not s.coordinator_token or len(s.coordinator_token) < MIN_TOKEN:
        raise LiveConfigError(f"COORDINATOR_TOKEN must be set (>= {MIN_TOKEN} chars)")
    if s.coordinator_admin_token is not None and len(s.coordinator_admin_token) < MIN_TOKEN:
        raise LiveConfigError(f"COORDINATOR_ADMIN_TOKEN must be >= {MIN_TOKEN} chars when set")
    if s.coordinator_plan_file is None:
        raise LiveConfigError("COORDINATOR_PLAN_FILE must be set")


class LiveBackend:
    def __init__(
        self,
        settings: Settings,
        manager: RunManager,
        ingest: TelemetryIngest,
        client: CoordinatorClient | None = None,
    ) -> None:
        validate_settings(settings)
        assert settings.coordinator_url and settings.coordinator_token
        assert settings.coordinator_plan_file is not None
        self.s, self.mgr, self.ingest = settings, manager, ingest
        self.plans = load_plans(settings.coordinator_plan_file)
        self.client = client or CoordinatorClient(
            settings.coordinator_url,
            settings.coordinator_token,
            settings.coordinator_admin_token,
            settings.live_request_timeout,
        )
        self._create_lock = asyncio.Lock()
        self.pulled = 0  # canonical records admitted from the coordinator (diagnostics)

    # ------------------------------------------------------------------ requests
    def resolve_plan(self, body: Any) -> tuple[RunConfig, str]:
        """Split a POST /v1/runs body into (run config, allowlisted plan name)."""
        if not isinstance(body, dict):
            raise Rejected(422, "body must be a JSON object")
        raw = dict(body)
        if FORBIDDEN_BODY_KEYS & set(raw):
            raise Rejected(422, "node_urls are server-side only and are not accepted")
        name = raw.pop("plan", None)
        if name is None:
            if "default" in self.plans:
                name = "default"
            elif len(self.plans) == 1:
                name = next(iter(self.plans))
            else:
                raise Rejected(422, {"plan": "required", "allowed": sorted(self.plans)})
        if not isinstance(name, str) or name not in self.plans:
            # inline plan bodies (dict) and unknown names alike are refused
            raise Rejected(
                422,
                {"plan": "must be one of the configured plan names", "allowed": sorted(self.plans)},
            )
        try:
            return RunConfig.model_validate(raw), name
        except ValueError as e:
            raise Rejected(422, f"invalid run config: {e}") from None

    async def _call(
        self, method: str, path: str, body: Any = None, timeout: float | None = None
    ) -> tuple[int, dict[str, Any]]:
        return await asyncio.to_thread(self.client.request, method, path, body, timeout=timeout)

    async def create(self, key: str, config: RunConfig, plan_name: str) -> tuple[Run, bool]:
        fingerprint = config.model_dump_json() + "\n" + plan_name
        async with self._create_lock:
            existing = self.mgr.precheck(key, config, fingerprint)
            if existing is not None:
                return existing, False
            try:
                code, out = await self._call(
                    "POST",
                    "/v1/runs",
                    {"run_config": config.model_dump(mode="json"), "plan_name": plan_name},
                )
            except UpstreamError:
                raise Rejected(502, "coordinator unreachable") from None
            if code == 409:
                raise Conflict(f"coordinator refused: {out.get('error', 'conflict')}")
            if code != 201:
                detail = out.get("detail") or out.get("error") or "rejected"
                raise Rejected(code if 400 <= code < 500 else 502, detail)
            st = await self._status(config.run_id)
            run, _ = self.mgr.register(
                key,
                config,
                git_sha=str(st.get("commit")) if st else None,
                plan=plan_name,
                fingerprint=fingerprint,
            )
            if st:
                self._mirror(run, st)
            run.task = asyncio.get_running_loop().create_task(self._drive(run))
            return run, True

    async def _status(self, run_id: str) -> dict[str, Any] | None:
        code, st = await self._call("GET", f"/v1/runs/{run_id}")
        return st if code == 200 else None

    async def command(
        self, run: Run, command: str, command_id: str, expected_revision: int
    ) -> dict[str, Any]:
        if command_id in run.commands:
            return run.commands[command_id]
        if run.status not in ACTIVE:
            raise Conflict(f"cannot {command} a run that is {run.status}")
        body = {
            "command_id": command_id,
            "command": command,
            "expected_revision": expected_revision,
        }
        try:
            code, out = await self._call("POST", f"/v1/runs/{run.config.run_id}/commands", body)
        except UpstreamError:
            raise Rejected(502, "coordinator unreachable") from None
        if code == 200:
            self._mirror(run, out)
            result = run.view()
            run.commands[command_id] = result
            return result
        if code in (404, 409):
            raise Conflict(str(out.get("error", "command refused")))
        raise Rejected(code if 400 <= code < 500 else 502, out.get("detail") or out.get("error"))

    async def readiness(self) -> tuple[bool, dict[str, Any]]:
        """Coordinator reachable and at least one node ready; says nothing about runs (A11)."""
        try:
            code, out = await self._call("GET", "/readyz", timeout=2.0)
        except UpstreamError:
            return False, {"coordinator": "unreachable", "nodes_ready": 0}
        raw_nodes = out.get("nodes")
        nodes: dict[str, Any] = raw_nodes if isinstance(raw_nodes, dict) else {}
        ready_nodes = sum(1 for v in nodes.values() if v is True)
        if code in (401, 403):
            return False, {"coordinator": "unauthorized", "nodes_ready": 0}
        ok = code == 200 and out.get("ready") is True and ready_nodes >= 1
        return ok, {
            "coordinator": "ok" if ok else "not_ready",
            "nodes_ready": ready_nodes,
            "nodes_total": len(nodes),
            "simulator": sim.get("available")
            if isinstance(sim := out.get("simulator"), dict)
            else None,
        }

    # ------------------------------------------------------------------ mirroring
    def _mirror(self, run: Run, st: dict[str, Any]) -> None:
        """Apply coordinator status to the API run (never moves a terminal run backwards)."""
        status = st.get("status")
        if status not in (
            "created",
            "starting",
            "running",
            "paused",
            "stopping",
            "completed",
            "failed",
            "interrupted",
        ):
            return
        rev = int(st.get("revision", run.revision))
        if isinstance(st.get("tick"), int):
            run.tick = st["tick"]
        if run.status in TERMINAL or rev < run.revision:
            return
        if status == run.status:
            run.revision = rev  # e.g. a step token bumps the revision without a status change
            return
        reason = st.get("stop_reason") or st.get("error")
        if status in TERMINAL:
            self._finish(run, status, reason, rev)
        else:
            self.mgr._set(run, status, reason, rev)  # noqa: SLF001 - same package

    def _finish(self, run: Run, status: Status, reason: str | None, rev: int | None) -> None:
        if run.final is None and run.last_world is not None:
            run.final = self.mgr.snapshot_event(run)["snapshot"]
        self.mgr._set(run, status, reason, rev)  # noqa: SLF001

    # ------------------------------------------------------------------ event pull
    def _context(self, run: Run, st: dict[str, Any], episode: int) -> dict[str, Any]:
        return {
            "commit": str(st.get("commit") or run.commit or "unknown"),
            "config_hash": str(st.get("config_hash") or "unknown"),
            "seed": int(run.config.seeds.get("env", 0)),
            "host": "coordinator",
            "boot_id": str(st.get("boot_id") or "coordinator"),
            "episode": episode,
        }

    async def _pull(self, run: Run, st: dict[str, Any], cursor: int) -> tuple[int, int]:
        """Drain pending coordinator events. Returns (new cursor, records seen)."""
        seen = 0
        max_ticks = run.config.budgets.max_ticks
        while True:
            code, page = await self._call(
                "GET", f"/v1/runs/{run.config.run_id}/events?after_sequence={cursor}&limit=500"
            )
            events = page.get("events") if code == 200 else None
            if not isinstance(events, list):
                raise UpstreamError(f"events:{code}")
            if not events:
                return cursor, seen
            groups: dict[int, list[Any]] = {}
            for ev in events:
                tick = ev.get("sim_tick", 0) if isinstance(ev, dict) else 0
                # global index (A7): post-step records of episode e span e*max+1 .. e*max+max
                groups.setdefault(max(int(tick) - 1, 0) // max_ticks, []).append(ev)
            for episode, items in groups.items():
                res = self.ingest.admit(items, self._context(run, st, episode))
                if res["rejected"]:
                    log.warning("coordinator records rejected: %d", len(res["rejected"]))
            self.pulled += len(events)
            seen += len(events)
            cursor = max(cursor, int(events[-1]["sequence"]))

    async def _drive(self, run: Run) -> None:
        rid, cursor, failures = run.config.run_id, 0, 0
        while True:
            try:
                st = await self._status(rid)
                if st is None:
                    raise UpstreamError("status")
                cursor, _ = await self._pull(run, st, cursor)
                self._mirror(run, st)
                failures = 0
            except UpstreamError:
                failures += 1
            except Exception as e:  # HTTPException(503) from a full ingest queue, etc.
                failures += 0 if getattr(e, "status_code", None) == 503 else 1
                log.warning("live pull deferred: %s", type(e).__name__)
            if failures >= self.s.live_max_failures:
                self._finish(run, "failed", "coordinator_unreachable", None)
                return
            if run.status in TERMINAL:
                return
            await asyncio.sleep(self.s.live_poll_interval)
