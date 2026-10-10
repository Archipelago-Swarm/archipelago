"""Peak-RSS measurement for a 4-node-sized run (not a test; run by hand).

    uv run python tests/learning/measure_rss.py [--nodes 4] [--steps 1000] [--procs]

Default: N TorchLearners (28-32-5 MLP, capacity 5000, batch 32, 1 thread) with a full replay,
trained --steps steps each, one checkpoint each, all in ONE process; prints that process's peak
RSS. With --procs: N separate processes (one learner each, as in a real deployment), prints the
per-process and summed peak RSS. Also prints the RSS right after `import torch` for reference.
Output is JSON on stdout. Linux only (ru_maxrss in KiB).
"""

import argparse
import json
import resource
import subprocess
import sys
import tempfile


def peak_mib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def run_learners(nodes, steps):
    import numpy as np
    from archipelago_learning import TorchLearner

    base = peak_mib()  # after import torch + package
    rng = np.random.default_rng(0)
    learners = [
        TorchLearner(f"node-{i:02d}", 28, 5, hidden=32, seed=i, capacity=5000, threads=1)
        for i in range(nodes)
    ]
    for learner in learners:
        for _ in range(learner.capacity):
            o, o2 = rng.random(28, dtype=np.float32), rng.random(28, dtype=np.float32)
            learner.observe(o, int(rng.integers(5)), float(rng.random()), o2, False)
    for _ in range(steps):
        for learner in learners:
            learner.train_step()
    with tempfile.TemporaryDirectory() as d:
        for i, learner in enumerate(learners):
            learner.save_generation(f"{d}/{i}")
    return {
        "nodes": nodes,
        "steps": steps,
        "after_import_peak_mib": round(base, 1),
        "peak_rss_mib": round(peak_mib(), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, default=4)
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("--procs", action="store_true")
    ap.add_argument("--child", action="store_true")
    a = ap.parse_args()
    if a.child or not a.procs:
        import torch  # noqa: F401  (counted in the after-import figure)

        print(json.dumps(run_learners(1 if a.child else a.nodes, a.steps)))
        return
    cmd = [sys.executable, __file__, "--child", "--steps", str(a.steps)]
    ps = [subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True) for _ in range(a.nodes)]
    outs = [json.loads(p.communicate()[0]) for p in ps]
    per = [o["peak_rss_mib"] for o in outs]
    print(
        json.dumps(
            {"processes": a.nodes, "per_process_peak_mib": per, "sum_peak_mib": round(sum(per), 1)}
        )
    )


if __name__ == "__main__":
    main()
