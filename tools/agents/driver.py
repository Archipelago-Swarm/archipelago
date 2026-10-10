"""Never-exiting overnight driver around night.py.

A: waits for the active run's reports (B's push included), merges `review` branches into
main behind the full check gate, re-plans from BOARD.md dependencies, expires the old run,
launches the next one. B: rejoins each new run published by A. Operator enabled merging
by explicit instruction; failed gates leave main untouched.
shortcut: no per-process recovery of a crashed night.py mid-run, rerun the driver.
"""
import argparse, json, re, shutil, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cleanup_branches import cleanup as cleanup_branches

ROOT = Path(__file__).resolve().parents[2]
RT = ROOT / ".agent-runtime"
STATE = RT / "driver.json"
COORD = "agent-coordination"
MAX_ATTEMPTS = 6
B_WAIT_MIN = 90
# T06 forked from main after a carry-name collision. Preserve the complete
# earlier implementation until a later T06 branch descends from this recovery.
RECOVERY_SOURCES = {"T06": "agent/B/T06/reconciled-20261010"}


def sh(*a, check=True, cwd=ROOT, **k):
    r = subprocess.run(a, cwd=cwd, capture_output=True, text=True, **k)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(a)}: {r.stderr.strip() or r.stdout.strip()}")
    return r


def git(*a, check=True):
    return sh("git", *a, check=check).stdout.strip()


def now():
    return datetime.now(timezone.utc)


def log(msg):
    print(f"[driver {now():%H:%M:%SZ}] {msg}", flush=True)


def active():
    for _ in range(4):  # a concurrent fetch (mail watcher) can lose the ref lock
        if sh("git", "fetch", "-q", "origin", COORD, check=False).returncode == 0:
            break
        time.sleep(3)
    else:
        return None
    r = sh("git", "show", f"FETCH_HEAD:agents/coordination/active.json", check=False)
    return json.loads(r.stdout) if r.returncode == 0 else None


def report(run, machine):
    sh("git", "fetch", "-q", "origin", check=False)
    r = sh("git", "show", f"origin/agent/{machine}/{run}/report:agents/runs/{run}-{machine}.md", check=False)
    if r.returncode:
        return None
    return dict(re.findall(r"^- (T\d\d): (\w+);", r.stdout, re.M))


def board():
    rows = {}
    for line in (ROOT / "agents/tasks/BOARD.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| \[(T\d\d)\]\(\S+\) \| (\w) \| ([^|]*)\|", line)
        if m:
            rows[m[1]] = (m[2], re.findall(r"T\d\d", m[3]))
    return rows


def card_paths(task):
    text = (ROOT / f"agents/tasks/{task}.md").read_text(encoding="utf-8")
    m = re.search(r"Allowed paths: (.+)", text)
    return [p.strip(" `") for p in m[1].split(",")]


def load():
    state = json.loads(STATE.read_text()) if STATE.exists() else {"done": [], "attempts": {}}
    # A new checkout has no local driver state. Reconcile with the integrated
    # board before dispatching so already-merged work is never reassigned.
    for line in (ROOT / "agents/tasks/BOARD.md").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\| \[(T\d\d)\]\(\S+\) \| [AB] \| [^|]*\| ([^|]*)\|", line)
        if match and match[2].strip().startswith(("done", "review: merged")):
            if match[1] not in state["done"]:
                state["done"].append(match[1])
    return state


def save(s):
    RT.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1))


def gate():
    bash = None
    if sys.platform == "win32":
        git_exe = shutil.which("git")
        candidates = [Path(git_exe).resolve().parents[1] / "bin" / "bash.exe"] if git_exe else []
        candidates += [Path("C:/Program Files/Git/bin/bash.exe"), Path("C:/msys64/usr/bin/bash.exe")]
        bash = next((str(candidate) for candidate in candidates if candidate.is_file()), None)
    else:
        bash = shutil.which("bash")
    if not bash:
        raise RuntimeError("Git Bash is required for scripts/check.sh")
    return sh(bash, "scripts/check.sh", check=False, timeout=1800).returncode == 0


def integrate(run, results, s):
    """results: {task: (machine, status)}; merges reviewed branches, bumps attempts otherwise."""
    git("checkout", "-q", "main")
    git("pull", "-q", "--ff-only")
    for task, (m, status) in sorted(results.items()):
        if task in s["done"]:
            continue
        branch = f"origin/agent/{m}/{run}/{task}"
        ok = False
        if status == "review":
            r = sh("git", "merge", "--no-ff", "-q", "-m", f"Merge {task} ({run}, gated)", branch, check=False)
            if r.returncode == 0 and gate():
                ok = True
            else:
                git("merge", "--abort", check=False)
                git("reset", "-q", "--hard", "origin/main")
                log(f"{task}: merge or gate failed, main untouched")
        if ok:
            git("push", "-q", "origin", "main")
            s["done"].append(task)
            log(f"{task}: merged")
        else:
            s["attempts"][task] = s["attempts"].get(task, 0) + 1
    save(s)


def next_plan(run_hint, last, s):
    tasks, rows = [], board()
    for task, (m, deps) in rows.items():
        if task in s["done"] or s["attempts"].get(task, 0) >= MAX_ATTEMPTS:
            continue
        if not all(d in s["done"] for d in deps):
            continue
        entry = {"id": task, "machine": m, "paths": card_paths(task)}
        prior = (last or {}).get(task)
        if not prior:
            # A or B may have finished a prior run while the driver was offline.
            # Carry its newest checkpoint instead of forking unfinished work.
            refs = git("for-each-ref", "--sort=-committerdate", "--format=%(refname:short)",
                       f"refs/remotes/origin/agent/{m}/*/{task}",
                       f"refs/remotes/origin/agent/{m}/{task}/*").splitlines()
            if refs:
                prior_ref = recovery_ref(task, refs[0])
                carry = f"agent/{m}/{task}/carry-{run_hint or now().strftime('%Y%m%dT%H%M%S')}"
                if sh("git", "push", "-q", "origin", f"{prior_ref}:refs/heads/{carry}", check=False).returncode:
                    continue
                entry["source_branch"] = carry
        if prior:  # keep the previous owner; carry over the previous run's branch, never restart from main
            entry["machine"] = prior[0]
            carry = f"agent/{prior[0]}/{task}/carry-{run_hint}-{s['attempts'].get(task, 0)}"
            source_ref = recovery_ref(task, f"origin/agent/{prior[0]}/{run_hint}/{task}")
            r = sh("git", "push", "-q", "origin", f"{source_ref}:refs/heads/{carry}", check=False)
            if r.returncode:
                log(f"{task}: could not preserve {run_hint} checkpoint; skipping task")
                continue
            entry["source_branch"] = carry
        tasks.append(entry)
    return tasks


def recovery_ref(task, candidate):
    source = RECOVERY_SOURCES.get(task)
    if not source:
        return candidate
    recovery = f"origin/{source}"
    if sh("git", "merge-base", "--is-ancestor", recovery, candidate, check=False).returncode == 0:
        return candidate
    return recovery


def report_machines(plan):
    """Wait for every assigned machine, including one preparing its first branch."""
    return set(plan.values())


def publish(tasks):
    git("checkout", "-q", "main")
    (ROOT / "agents/operations/night-plan.json").write_text(
        json.dumps({"schema_version": 1, "tasks": tasks}, indent=2) + "\n"
    )
    git("add", "-A")
    if sh("git", "diff", "--cached", "--quiet", check=False).returncode:  # retry-safe: plan may already be committed
        git("commit", "-q", "-m", "Driver: next overnight plan\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
    git("push", "-q", "origin", "main")
    wt = RT / "coord-expire"
    for attempt in range(5):  # B also writes this branch (mailbox), so refetch and retry on a lost race
        sh("git", "worktree", "remove", "--force", str(wt), check=False)
        git("fetch", "-q", "origin", COORD)
        git("worktree", "add", "-q", str(wt), "--detach", f"origin/{COORD}")
        f = wt / "agents/coordination/active.json"
        d = json.loads(f.read_text())
        d["stop_at_utc"] = "2026-01-01T00:00:00Z"
        f.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
        sh("git", "add", "-A", cwd=wt)
        if sh("git", "diff", "--cached", "--quiet", cwd=wt, check=False).returncode:
            sh("git", "commit", "-q", "-m", "Driver: expire completed run", cwd=wt)
        if sh("git", "push", "-q", "origin", f"HEAD:{COORD}", cwd=wt, check=False).returncode == 0:
            break
        time.sleep(2)
    else:
        raise RuntimeError("could not expire the active run after 5 attempts")
    sh("git", "worktree", "remove", "--force", str(wt), check=False)
    (RT / "active-plan.json").unlink(missing_ok=True)


def driver_a(a):
    until = datetime.fromisoformat(a.until_utc.replace("Z", "+00:00"))
    s = load()
    sh("npm", "ci", check=False, shell=True)
    cur = active()
    last_run = a.resume_run or (cur["run_id"] if cur else None)
    plan = {t["id"]: t["machine"] for t in (cur or {}).get("tasks", [])}
    if a.resume_run:  # integrate that run from its own report only; its peer never joined
        plan = {t: "A" for t in (report(a.resume_run, "A") or {})}
    started = now()
    while True:
        try:
            if last_run:
                log(f"waiting on reports for {last_run}")
                results, t0 = {}, None
                while True:
                    # A peer may be polling or preparing its first branch. Keep the
                    # published assignment stable until its report or the wait limit.
                    peers = report_machines(plan)
                    reps = {m: report(last_run, m) for m in peers}
                    if all(reps.values()):
                        break
                    # A crashed supervisor may have pushed checkpoints but no
                    # report. Once its lease expires, carry those branches into
                    # the next run instead of waiting forever or starting over.
                    if cur and now() >= datetime.fromisoformat(cur["stop_at_utc"].replace("Z", "+00:00")):
                        log("run expired without every report; preserving pushed task branches")
                        break
                    if reps.get("A") and t0 is None:
                        t0 = now()
                    if t0 and now() - t0 > timedelta(minutes=B_WAIT_MIN):
                        log("peer report overdue; proceeding without it")
                        break
                    time.sleep(60)
                for m, rep in reps.items():
                    for t, st in (rep or {}).items():
                        results[t] = (m, st)
                for t, m in plan.items():
                    if t not in results and sh("git", "ls-remote", "--exit-code", "--heads", "origin", f"agent/{m}/{last_run}/{t}", check=False).returncode == 0:
                        results[t] = (m, "in_progress")
                integrate(last_run, results, s)
                try:
                    archived, removed = cleanup_branches(ROOT, apply=True)
                    log(f"branch cleanup: archived {archived} reports; removed {removed} redundant refs")
                except Exception as error:
                    # Cleanup is maintenance, never a reason to lose a run's handoff.
                    log(f"branch cleanup deferred: {error}")
                prior = results
            else:
                prior = {}
            tasks = next_plan(last_run, prior, s)
            remaining = (until - now()).total_seconds() / 3600
            if not tasks or remaining < 0.4:
                log(f"nothing runnable (done={s['done']}); idling 5 min")
                last_run = None
                time.sleep(300)
                continue
            publish(tasks)
            log(f"launching plan {[t['id'] for t in tasks]} for {remaining:.1f}h")
            subprocess.run(
                [sys.executable, "tools/agents/night.py", "--machine", "A", "--billing", "subscription",
                 "--hours", f"{remaining:.2f}", "--max-rounds", str(a.max_rounds)],
                cwd=ROOT,
            )
            saved = RT / "active-plan.json"  # written by night.py; independent of any fetch
            cur = json.loads(saved.read_text()) if saved.exists() else active()
            last_run = cur["run_id"] if cur else None
            plan = {t["id"]: t["machine"] for t in (cur or {}).get("tasks", [])}
            prior = {}
        except Exception as e:  # keep the loop alive; surface the reason
            log(f"error: {e}; retrying in 120s")
            time.sleep(120)


def driver_b(a):
    seen = None
    while True:
        try:
            cur = active()
            if cur and cur["run_id"] != seen and datetime.fromisoformat(cur["stop_at_utc"].replace("Z", "+00:00")) > now():
                seen = cur["run_id"]
                git("checkout", "-q", "main")
                git("pull", "-q", "--ff-only")
                log(f"joining {seen}")
                subprocess.run([sys.executable, "tools/agents/night.py", "--machine", "B", "--billing", "subscription",
                                "--max-rounds", str(a.max_rounds)], cwd=ROOT)
        except Exception as e:
            log(f"error: {e}")
        time.sleep(60)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--machine", choices=["A", "B"], required=True)
    p.add_argument("--until-utc", default="2026-10-10T13:00:00Z")
    p.add_argument("--resume-run", default=None)
    p.add_argument("--max-rounds", type=int, default=10)
    a = p.parse_args()
    (driver_a if a.machine == "A" else driver_b)(a)
