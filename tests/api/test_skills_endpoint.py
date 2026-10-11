from pathlib import Path
from typing import Any

from test_api import make, mgr, start


def metric(seq: int, node: str, name: str, value: float, unit: str) -> dict[str, Any]:
    return {
        "sequence": seq,
        "kind": "metric_sample",
        "source_node_id": node,
        "metric": name,
        "value": value,
        "unit": unit,
    }


def test_skills_endpoint_folds_metrics_and_adoptions_per_node(tmp_path: Path) -> None:
    with make(tmp_path) as c:
        rid = start(c)["run_id"]
        mgr(c).get(rid).events.extend(
            [
                metric(101, "node-01", "skill.explore", 0.25, "score"),
                metric(102, "node-01", "skill_version.explore", 1, "source:node-01"),
                metric(103, "node-01", "skill.explore", 0.5, "score"),
                metric(104, "node-01", "skill_version.explore", 2, "source:node-02"),
                metric(105, "node-02", "reward", 1.0, "score"),
                {
                    "sequence": 106,
                    "kind": "learning_event",
                    "source_node_id": "node-01",
                    "transfer": "accepted",
                    "skill": "explore",
                    "skill_gain": 0.25,
                },
                {
                    "sequence": 107,
                    "kind": "learning_event",
                    "source_node_id": "node-01",
                    "transfer": "rejected",
                    "skill": "avoid",
                    "skill_gain": 0.0,
                },
            ]
        )
        body = c.get(f"/v1/runs/{rid}/skills").json()
        assert body["nodes"] == {
            "node-01": {"explore": {"proficiency": 0.5, "version": 2, "source": "node-02"}}
        }
        assert body["adoptions"] == [
            {"node": "node-01", "skill": "explore", "gain": 0.25, "sequence": 106}
        ]
        assert c.get("/v1/runs/nope/skills").status_code == 404
