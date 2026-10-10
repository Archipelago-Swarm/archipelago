"""Coordinator service: run registry, validation, persistence and readiness (transport-free)."""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from archipelago_contracts.models import MetricSample
from pydantic import ValidationError

from . import sim
from .models import MAX_RUN_ID, CommandBody, CreateRun
from .nodeclient import NodeClient
from .runner import ACTIVE, Run
from .settings import Settings
from .sim import SimulatorUnavailable
from .spool import EventSpool, safe_name

Json = dict[str, Any]


class Coordinator:
    def __init__(
        self,
        settings: Settings,
        *,
        adapter_factory: Callable[[Json], Any] | None = None,
        sim_check: Callable[[], tuple[bool, str]] | None = None,
        client: NodeClient | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.adapter_factory = adapter_factory or sim.adapter_factory
        self.sim_check = sim_check or sim.check
        ok, why = self.sim_check()
        if not ok and settings.production:
            # fail visibly at startup: there is no fixture fallback to degrade to
            raise SimulatorUnavailable(f"real simulator unavailable: {why}")
        self.boot_id = uuid.uuid4().hex[:8]
        self.spool = EventSpool(settings.data_dir / "events", self.boot_id)
        self.client = client or NodeClient(settings.node_token)
        self.runs_dir = settings.data_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self.current: Run | None = None
        self.summaries: dict[str, Json] = {}
        self._recover()

    # ----------------------------------------------------------- persistence
    def _manifest_path(self, run_id: str) -> Any:
        return self.runs_dir / safe_name(run_id) / "manifest.json"

    def _persist(self, run_id: str, doc: Json) -> None:
        p = self._manifest_path(run_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(doc, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)

    def _on_state(self, run: Run) -> None:
        doc = {
            **run.status_dict(),
            "boot_id": self.boot_id,
            "run_config": run.cfg.model_dump(mode="json"),
            "plan": run.plan.model_dump(mode="json"),
        }
        with self._state_lock:
            self.summaries[run.run_id] = doc
            self._persist(run.run_id, doc)

    def _recover(self) -> None:
        """A run that was active when a previous process died is marked interrupted."""
        for p in sorted(self.runs_dir.glob("*/manifest.json")):
            try:
                doc = json.loads(p.read_text())
                rid = doc["run_id"]
            except (OSError, ValueError, KeyError):
                continue
            if doc.get("status") in ACTIVE:
                last = self.spool.page(rid, max(self.spool.latest_sequence(rid) - 1, 0), 1)
                if last and last["events"]:  # the manifest is only written at state changes
                    doc["tick"] = max(int(doc.get("tick", 0)), last["events"][-1]["sim_tick"])
                doc["status"] = "interrupted"
                doc["revision"] = int(doc.get("revision", 0)) + 1
                doc["stop_reason"] = "coordinator_restart"
                self.spool.emit(
                    rid,
                    int(doc.get("tick", 0)),
                    None,
                    lambda b: MetricSample(
                        **b, metric="run_interrupted", value=1.0, unit="count", phase="other"
                    ),
                )
                doc["latest_sequence"] = self.spool.latest_sequence(rid)
                self._persist(rid, doc)
            self.summaries[rid] = doc

    # ----------------------------------------------------------- validation
    def _validate(self, req: CreateRun) -> str | None:
        cfg, plan = req.run_config, req.plan
        if len(cfg.run_id) > MAX_RUN_ID:
            return f"run_id longer than {MAX_RUN_ID} characters"
        if cfg.reward_id not in sim.reward_ids():
            return f"unknown reward_id {cfg.reward_id!r}"
        ids = [n.node_id for n in cfg.nodes]
        if len(set(ids)) != len(ids):
            return "duplicate node ids in run_config"
        if set(plan.node_urls) != set(ids):
            missing = sorted(set(ids) - set(plan.node_urls))
            extra = sorted(set(plan.node_urls) - set(ids))
            return f"plan.node_urls must match run_config nodes (missing {missing}, extra {extra})"
        for n, url in plan.node_urls.items():
            u = urlsplit(url)
            if u.scheme not in ("http", "https") or not u.netloc:
                return f"bad url for {n}"
        known = set(ids)
        for w in plan.fault_schedule:
            if w.start_tick >= w.end_tick:
                return "fault window must have start_tick < end_tick"
            for a, b in w.cut_links:
                if a == b or a not in known or b not in known:
                    return f"bad cut link {a!r}-{b!r}"
        if plan.kill_node and plan.kill_node.node_id not in known:
            return "kill_node names an unknown node"
        o = plan.telemetry_outage
        if o and o.start_tick >= o.end_tick:
            return "telemetry_outage must have start_tick < end_tick"
        try:  # non-distinct or out-of-grid starts are rejected by the adapter itself
            probe = self.adapter_factory(self.settings.world_kwargs)
            probe.reset(cfg)
            probe.close()
        except (ValueError, TypeError) as e:
            return str(e)
        return None

    # ----------------------------------------------------------------- API
    def create_run(self, body: Any) -> tuple[int, Json]:
        try:
            req = CreateRun.model_validate(body)
        except ValidationError as e:
            return 422, {"error": "invalid_request", "detail": _errors(e)}
        ok, why = self.sim_check()
        if not ok:
            return 503, {"error": "simulator_unavailable", "detail": why}
        problem = self._validate(req)
        if problem:
            return 422, {"error": "invalid_request", "detail": problem}
        rid = req.run_config.run_id
        with self._lock:
            if self.current is not None and self.current.status in ACTIVE:
                return 409, {"error": "run_active", "run_id": self.current.run_id}
            if rid in self.summaries or self.spool.known(rid):
                return 409, {"error": "run_exists", "run_id": rid}
            run = Run(
                cfg=req.run_config,
                plan=req.plan,
                settings=self.settings,
                spool=self.spool,
                client=self.client,
                adapter_factory=self.adapter_factory,
                on_state=self._on_state,
            )
            self.current = run
            self._on_state(run)
            run.start()
        return 201, {"run_id": rid, "status": run.status, "revision": run.revision}

    def _run_doc(self, run_id: str) -> Json | None:
        cur = self.current
        if cur is not None and cur.run_id == run_id:
            return cur.status_dict()
        return self.summaries.get(run_id)

    def get_run(self, run_id: str) -> tuple[int, Json]:
        doc = self._run_doc(run_id)
        if doc is None:
            return 404, {"error": "unknown_run"}
        doc = {k: v for k, v in doc.items() if k not in ("run_config", "plan")}
        return 200, doc

    def command(self, run_id: str, body: Any) -> tuple[int, Json]:
        try:
            cmd = CommandBody.model_validate(body)
        except ValidationError as e:
            return 422, {"error": "invalid_request", "detail": _errors(e)}
        cur = self.current
        if cur is None or cur.run_id != run_id:
            if run_id in self.summaries:
                return 409, {"error": "run_not_active", "status": self.summaries[run_id]["status"]}
            return 404, {"error": "unknown_run"}
        return cur.apply_command(cmd.model_dump())

    def events(self, run_id: str, after: int, limit: int) -> tuple[int, Json]:
        page = self.spool.page(run_id, after, limit)
        if page is None:
            return 404, {"error": "unknown_run"}
        return 200, page

    def snapshot(self, run_id: str) -> tuple[int, Json]:
        cur = self.current
        if cur is None or cur.run_id != run_id:
            if run_id in self.summaries:
                return 404, {"error": "snapshot_unavailable"}
            return 404, {"error": "unknown_run"}
        snap = cur.privileged_snapshot()
        if snap is None:
            return 404, {"error": "snapshot_unavailable"}
        return 200, snap.model_dump(mode="json")

    def readiness(self) -> tuple[int, Json]:
        ok, why = self.sim_check()
        urls = dict(self.settings.node_urls)
        cur = self.current
        if cur is not None and cur.status in ACTIVE:
            urls.update(cur.plan.node_urls)
        replies = self.client.fanout(
            {
                n: (
                    lambda u=u: self.client.call(u, "GET", "/v1/status", None, 1.0, keepalive=False)
                )
                for n, u in urls.items()
            },
            1.5,
        )
        nodes = {n: bool(r is not None and r.ok) for n, r in replies.items()}
        ready = ok and any(nodes.values())
        body = {
            "ready": ready,
            "simulator": {"available": ok, "detail": why},
            "nodes": nodes,
            "boot_id": self.boot_id,
        }
        return (200 if ready else 503), body

    def close(self) -> None:
        """Stop background work. An active run is left active on disk (so a restart marks it
        interrupted), exactly as after a crash."""
        cur = self.current
        if cur is not None:
            cur.abort()
        self.client.close()
        self.spool.close()


def _errors(e: ValidationError) -> list[Json]:
    return [
        {"loc": [str(x) for x in err["loc"]], "msg": err["msg"]}
        for err in e.errors(include_url=False, include_input=False, include_context=False)
    ]
