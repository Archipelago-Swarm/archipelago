import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from archipelago_mission.serve import Handler


def test_live_endpoints_simulate_on_the_spot():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/api/mission"
    try:
        a = json.load(urllib.request.urlopen(f"{base}/run?seed=1002"))
        b = json.load(urllib.request.urlopen(f"{base}/run?seed=1002"))
        assert a == b and a["frames"][-1]["mission"]["status"] in ("SUCCESS", "FAILED")
        raw = urllib.request.urlopen(f"{base}/stream?seed=1002&tps=1000").read().decode()
        assert raw.startswith("event: meta") and "event: tick" in raw and raw.rstrip().split("\n")[-2] == "event: end"
        ticks = [json.loads(x[6:]) for x in raw.split("\n") if x.startswith("data: ")][1:-1]
        assert ticks[-1]["frame"]["mission"] == a["frames"][-1]["mission"]  # stream == batch run
        assert sum(len(t["events"]) for t in ticks) == len(a["events"])
    finally:
        srv.shutdown()
