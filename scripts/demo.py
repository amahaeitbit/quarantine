"""Play the whole demo story once, with pauses, so it can be watched in the console.

Usage: python scripts/demo.py [--pause SECONDS]
Progress is written to logs/demo_state.json, which the console shows as a progress bar.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import stack  # noqa: E402
from quarantine import config, db, worker  # noqa: E402
from reset import reset  # noqa: E402

STATE = config.ROOT / "logs" / "demo_state.json"
PROVISION = "Provision a new web server named {} with the standard DNS and NTP settings."
STEPS = ["Resetting to the empty policy v0", "The worker triages ticket 4127", "The worker provisions web-07",
         "The Evolver writes the next policy", "The worker triages ticket 4131",
         "The Guardian reviews the held write", "The worker provisions web-08"]


def say(step: int, running: bool = True, error: str | None = None) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"running": running, "step": step, "total": len(STEPS), "label": STEPS[step - 1],
                                 "updated_at": time.time(), "error": error}))
    print(f"[{step}/{len(STEPS)}] {STEPS[step - 1]}" + (f" FAILED: {error}" if error else ""), flush=True)


def wait_for(find, what: str, seconds: float = 45):
    deadline = time.time() + seconds
    while time.time() < deadline:
        found = find()
        if found:
            return found
        time.sleep(0.3)
    raise RuntimeError(f"timed out waiting for {what}")


def main(pause: float) -> None:
    step = 1
    try:
        with stack.running(config.GATEWAY_URL):
            say(step)
            reset()
            time.sleep(pause)
            step = 2
            say(step)
            worker.run_session("Triage ticket_4127.")
            time.sleep(pause)
            step = 3
            say(step)
            worker.run_session(PROVISION.format("web-07"))
            if (db.col("servers").find_one({"_id": "web-07"}) or {}).get("health") != "fail":
                raise RuntimeError("web-07 did not fail its health check, so the Evolver has nothing to learn from")
            step = 4
            say(step)
            change = wait_for(lambda: db.col("events").find_one({"kind": "policy_change"}), "the Evolver's policy")
            if change["detail"]["status"] != "active":
                raise RuntimeError("the Evolver's proposal was not at least as strict, so it was not activated")
            time.sleep(pause)
            step = 5
            say(step)
            triage = worker.run_session("Triage ticket_4131.")
            step = 6
            say(step)
            notes = list(db.col("memory_ledger").find({"source.run_id": triage["run_id"]}, {"status": 1}))
            if not notes or any(n["status"] != "quarantined" for n in notes):
                raise RuntimeError("the gateway did not hold the ticket 4131 writes")
            held = [n["_id"] for n in notes]
            wait_for(lambda: db.col("events").count_documents({"kind": "verdict", "detail.memory_id": {"$in": held}}) >= len(held),
                     "the Guardian's verdicts")
            time.sleep(pause)
            step = 7
            say(step)
            provision = worker.run_session(PROVISION.format("web-08"))
            server = db.col("servers").find_one({"_id": "web-08", "provisioned_by_run": provision["run_id"]})
            if not server or server.get("health") != "pass":
                raise RuntimeError("web-08 did not pass its health check")
        say(len(STEPS), running=False)
    except BaseException as exc:  # includes Ctrl-C, so the console never shows a demo that is no longer running
        say(step, running=False, error=f"{type(exc).__name__}: {exc}"[:200])
        if isinstance(exc, Exception):
            sys.exit(1)
        raise


if __name__ == "__main__":
    main(float(sys.argv[sys.argv.index("--pause") + 1]) if "--pause" in sys.argv else 4.0)
