"""Grounded decision explanations: every number comes from the stored decision record / weights.

``attribute`` is exact for this net: Q_a - Q_b = (relu(x W1 + b1)) (W2[:,a] - W2[:,b]), so the
local linearisation d(Q_a - Q_b)/dx = W1 diag(relu'(z)) (W2[:,a]-W2[:,b]) and input*gradient
contributions are the first-order share of each input feature. They are attributions of the
learned function, not statements about what the node "understood".
"""

from __future__ import annotations

import numpy as np

from .world import OBS_NAMES


def attribute(params: dict[str, np.ndarray], x, a: int, b: int, top: int = 3) -> list[dict]:
    x = np.asarray(x, np.float32)
    z = x @ params["w1"] + params["b1"]
    g = params["w1"] @ ((z > 0) * (params["w2"][:, a] - params["w2"][:, b]))
    c = x * g
    order = np.argsort(-np.abs(c))[:top]
    return [
        {
            "feature": OBS_NAMES[i],
            "value": round(float(x[i]), 3),
            "contribution": round(float(c[i]), 3),
        }
        for i in order
    ]


def explain(d: dict) -> str:
    """Human-readable summary of one decision record (derived only from its fields)."""
    o = d["observation_summary"]
    a = d["selected_action"]
    q = d["raw_policy_output"]["q_values"]
    p = d["action_distribution"]
    lines = [
        f"{d['node_id']} step {d['node_step']} selected {a} via {d['selection_method']}"
        f" (epsilon={d['epsilon']:.3f}, p={p[a]:.2f}); policy {d['active_policy_id']},"
        f" skill {d['active_skill_id'] or 'none'}.",
        "Q-values: "
        + ", ".join(f"{k}={v:+.2f}" for k, v in q.items())
        + f"; greedy={d['greedy_action']}.",
        f"Terrain toward {a}: slope/limit={o['slope_' + a]:+.2f},"
        f" look-ahead={o['ahead_' + a]:+.2f};"
        f" local roughness={o['roughness']:.2f}, clearance={o['clearance']:+.2f}.",
        f"Goal offset (dx,dy)=({o['goal_dx'] * 8:+.1f},{o['goal_dy'] * 8:+.1f}) cells.",
    ]
    at = d.get("attribution")
    if at:
        lines.append(
            f"Largest input contributions to Q({a}) - Q({at['versus']}): "
            + ", ".join(
                f"{t['feature']}={t['value']:+.2f} ({t['contribution']:+.2f})" for t in at["top"]
            )
        )
    r = d["reward_components"]
    lines.append(
        f"Outcome: reward {d['reward_after_action']:+.2f} ("
        + ", ".join(f"{k}={v:+.2f}" for k, v in r.items() if v)
        + ")"
        + (f"; move rejected: {d['executed']['rejected']}" if d["executed"]["rejected"] else "")
        + "."
        + f" experience_recorded={d['experience_recorded']},"
        + f" update={d['training_update_triggered']}"
        + f" (policy v{d['policy_version_before']}->v{d['policy_version_after']})."
    )
    return "\n".join(lines)
