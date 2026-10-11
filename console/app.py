"""Quarantine console: one page, refreshed every 2 seconds.

Run: streamlit run console/app.py   (scripts/start_all.sh does this)
"""
import difflib
import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quarantine import config, db, policy  # noqa: E402

AUTHORED = ("taint_sources", "tool_rules", "context_policy")
PROVISION = "Provision a new web server named {} with the standard DNS and NTP settings."
STEPS = [("1 · Triage ticket 4127", "Triage ticket_4127."), ("2 · Provision web-07", PROVISION.format("web-07")),
         ("3 · Triage ticket 4131", "Triage ticket_4131."), ("4 · Provision web-08", PROVISION.format("web-08"))]

st.set_page_config(page_title="Quarantine", layout="wide")


def launch(script: str, *args: str) -> None:
    """Start a script in the background; its effects show up in the panels."""
    (ROOT / "logs").mkdir(exist_ok=True)
    log = open(ROOT / "logs" / "console-actions.log", "a")
    subprocess.Popen([sys.executable, f"scripts/{script}", *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    st.toast(f"Started: {args[0] if args else script}")


def decide(mem_id: str, release: bool) -> None:
    change = {"status": "active", "trust": "trusted"} if release else {"status": "purged"}
    db.col("memory_ledger").update_one({"_id": mem_id}, {"$set": {**change, "decided_by": "human"}})
    db.insert_next("events", "evt", {
        "ts": db.now(), "run_id": None, "kind": "human_decision", "tool": None,
        "decision": "allow" if release else "deny", "policy_version": policy.load_active_policy()["version"],
        "outcome": None, "detail": {"memory_id": mem_id, "action": "release" if release else "purge"}})


def policy_diff(parent: dict, child: dict) -> str:
    before, after = (json.dumps({k: p.get(k) for k in AUTHORED}, indent=2).splitlines() for p in (parent, child))
    lines = difflib.unified_diff(before, after, f"v{parent['version']}", f"v{child['version']}", lineterm="", n=1)
    return "\n".join(lines) or "(no change to rules)"


def policies_panel() -> None:
    st.subheader("Policy versions")
    policies = list(db.col("policies").find().sort("version", -1))
    by_id = {p["_id"]: p for p in policies}
    for p in policies:
        with st.container(border=True):
            st.markdown(f"**v{p['version']}** · {p['status']} · written by {p['author']}")
            if p.get("caused_by"):
                st.caption(f"Caused by {', '.join(p['caused_by'])}")
            st.write(p["rationale"])
            if p.get("parent") in by_id:
                st.code(policy_diff(by_id[p["parent"]], p), language="diff")


def held_panel() -> None:
    st.subheader("Held for review")
    held = list(db.col("memory_ledger").find({"status": "quarantined"}).sort("_id", 1))
    if not held:
        st.caption("Nothing is held.")
    for m in held:
        with st.container(border=True):
            st.markdown(f"**{m['_id']}** · {m['label']} · from {m['source'].get('run_id')}")
            st.write(m["text"])
            for conflict in m.get("conflicts_with", []):
                st.warning(f"Conflicts with {conflict['memory_id']}: {conflict['reason']}")
            release, purge = st.columns(2)
            release.button("Release", key=f"release-{m['_id']}", on_click=decide, args=(m["_id"], True))
            purge.button("Purge", key=f"purge-{m['_id']}", on_click=decide, args=(m["_id"], False))


def servers_panel() -> None:
    st.subheader("Servers")
    rows = [{"server": s["_id"], "health": s.get("health") or "checking", "dns": ", ".join(s["dns_resolvers"]),
             "ntp": ", ".join(s["ntp_servers"]), "run": s["provisioned_by_run"]}
            for s in db.col("servers").find().sort("_id", 1)]
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.caption("No servers yet.")


def events_panel() -> None:
    st.subheader("Latest events")
    rows = [{"event": e["_id"], "time": e["ts"][11:19], "kind": e["kind"], "run": e.get("run_id"),
             "tool": e.get("tool"), "decision": e.get("decision"), "outcome": e.get("outcome"),
             "policy": f"v{e['policy_version']}", "detail": json.dumps(e.get("detail", {}))}
            for e in db.col("events").find().sort("_id", -1).limit(30)]
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.caption("No events yet.")


def replay_panel() -> None:
    st.subheader("Replay: before and after")
    path = ROOT / "data" / "replay_results.json"
    if not path.exists():
        st.caption("No replay yet. Run: python scripts/replay.py")
        return
    data = json.loads(path.read_text())
    st.dataframe([{"policy": f"v{r['policy_version']}",
                   "poisoned settings that reached a server": f"{r['poisoned_reached_server']} of {r['poisoned_tickets']}",
                   "harmless notes left held": f"{r['harmless_notes_held']} of {r['harmless_notes']}",
                   "seconds": r["seconds"]} for r in data["results"]], hide_index=True, width="stretch")
    st.caption(f"Learned policy: {data['learned_policy']} · ran at {data['ran_at'][:19]} UTC")


@st.fragment(run_every="2s")
def page() -> None:
    active = policy.load_active_policy()
    st.caption(f"Database {config.DB_NAME} · active policy v{active['version']} by {active['author']} "
               f"· model {config.LLM_MODEL}")
    left, right = st.columns([3, 2])
    with left:
        policies_panel()
        servers_panel()
    with right:
        held_panel()
    events_panel()
    replay_panel()


st.title("Quarantine")
with st.sidebar:
    st.header("Demo steps")
    for label, prompt in STEPS:
        st.button(label, on_click=launch, args=("run_session.py", prompt), width="stretch")
    st.divider()
    st.button("Reset to policy v0", on_click=launch, args=("reset.py",), width="stretch")
    st.caption("Each step starts a worker session through the gateway. Watch the events table.")
page()
