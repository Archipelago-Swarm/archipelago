# Diagnostic: API with the pre-fix _finish (no cached final snapshot), stop a sim2d run, subscribe to the stream.
import sys, tempfile, logging
sys.path[:0] = ["packages/adapters/sim2d", "packages/sim"]
logging.basicConfig(level=logging.DEBUG)
from pathlib import Path
from fastapi.testclient import TestClient
from archipelago_api.app import create_app, sim2d_factory
from archipelago_api.runs import RunManager
from archipelago_api.settings import Settings
from archipelago_sim2d.smoke import make_config
def old_finish(self, run, status, reason):
    if run.adapter is not None: run.adapter.close()
    self._set(run, status, reason)
RunManager._finish = old_finish
T = "diag-token-0123456789"; H = {"Authorization": f"Bearer {T}"}
s = Settings(api_token=T, data_dir=Path(tempfile.mkdtemp()), tick_interval=None)
with TestClient(create_app(s, sim2d_factory()), headers=H) as c:
    r = c.post("/v1/runs", json=make_config(7, 3).model_dump(mode="json"), headers={"Idempotency-Key": "k"}).json()
    for n, cm in enumerate(["pause", "stop"]):
        r = c.post(f"/v1/runs/{r['run_id']}/commands", json={"command": cm, "command_id": f"c{n}", "expected_revision": r["revision"]}).json()
    print("status", r["status"])
    with c.websocket_connect(f"/v1/runs/{r['run_id']}/stream") as ws: print(ws.receive_json())
