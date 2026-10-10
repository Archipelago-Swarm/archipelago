"""Node container entrypoint (infra-owned stand-in for the missing archipelago_node package).

Serves the T05 peer endpoint on the private network and persists a small checkpoint
(boots + last accepted seq per peer) in NODE_CHECKPOINT_DIR so restarts are observable.
"""

import json
import os
import time
from pathlib import Path

from archipelago_peer import PeerServer

me = os.environ["NODE_ID"]
port = int(os.environ.get("PEER_PORT", "9000"))
ids = os.environ.get("NODE_IDS", "node-01,node-02,node-03,node-04").split(",")
links = {(a, b) for a in ids for b in ids if a != b}
urls = {i: f"http://{i}:{port}" for i in ids}
ck = Path(os.environ.get("NODE_CHECKPOINT_DIR", "/node-data")) / "checkpoint.json"

state = json.loads(ck.read_text()) if ck.exists() else {"boots": 0, "seen": {}}
state["boots"] += 1


def save():
    tmp = ck.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, ck)  # atomic: a kill mid-write keeps the previous checkpoint


save()
srv = PeerServer(me, links, "0.0.0.0", port, urls=urls)  # noqa: S104 - private peers network only
print(f"{me} up boots={state['boots']}", flush=True)
while True:
    env = srv.receive()
    if env is None:
        time.sleep(0.2)
        continue
    state["seen"][env.src] = max(state["seen"].get(env.src, 0), env.seq)
    save()
