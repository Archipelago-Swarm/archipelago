"""Block until a new message for this machine appears in the coordination mailbox, print it, exit 0.

Run as a background task: its exit is the notification. Rerun after handling the mail.
Seen files are remembered in .agent-runtime/mail-seen-<M>.json so nothing is reported twice.
"""
import json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
M = sys.argv[1] if len(sys.argv) > 1 else "A"
SEEN = ROOT / ".agent-runtime" / f"mail-seen-{M}.json"
DIR = f"agents/coordination/mailbox/to-{M}"


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)


seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else None
while True:
    if git("fetch", "-q", "origin", "agent-coordination").returncode == 0:
        names = [n for n in git("ls-tree", "--name-only", "FETCH_HEAD", f"{DIR}/").stdout.split() if n.endswith(".md")]
        if seen is None:  # first run: only mail that arrives from now on is new
            seen = set(names) if "--all" not in sys.argv else set()
        new = sorted(set(names) - seen)
        if new:
            for n in new:
                print(f"NEW MAIL for {M}: {n}\n{git('show', f'FETCH_HEAD:{n}').stdout}\n", flush=True)
            SEEN.write_text(json.dumps(sorted(seen | set(new))))
            sys.exit(0)
        SEEN.write_text(json.dumps(sorted(seen)))
    time.sleep(30)
