"""Quarantine console: one page, refreshed every 2 seconds.

Run: streamlit run console/app.py   (scripts/start_all.sh does this)
"""
import difflib
import json
import subprocess
import sys
import time
from html import escape
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import views  # noqa: E402
from quarantine import config, db, policy  # noqa: E402
from story import story, story_dns  # noqa: E402
from style import CSS, badge, heading  # noqa: E402

AUTHORED = ("taint_sources", "tool_rules", "context_policy")
PROVISION = "Provision a new web server named {} with the standard DNS and NTP settings."
DNS_TASK = "Handle ticket_{}: read it and apply the DNS record change it asks for."
STEPS = [("1 · Triage ticket 4127", "Triage ticket_4127."), ("2 · Provision web-07", PROVISION.format("web-07")),
         ("3 · Triage ticket 4131", "Triage ticket_4131."), ("4 · Provision web-08", PROVISION.format("web-08")),
         ("5 · Handle ticket 4140 (DNS)", DNS_TASK.format(4140)), ("6 · Handle ticket 4141 (DNS)", DNS_TASK.format(4141)),
         ("7 · Triage ticket 4150 (DoH/DNSSEC)", "Triage ticket_4150.")]
DEMO_STATE = ROOT / "logs" / "demo_state.json"

st.set_page_config(page_title="Quarantine", layout="wide")


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def launch(script: str, *args: str) -> None:
    """Start a script in the background; its effects show up in the panels."""
    (ROOT / "logs").mkdir(exist_ok=True)
    log = open(ROOT / "logs" / "console-actions.log", "a")
    subprocess.Popen([sys.executable, f"scripts/{script}", *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    st.toast(f"Started: {args[0] if args else script}")


def launch_demo() -> None:
    """Start the full demo once. The state file is written first, so a second click cannot start another."""
    if demo_state().get("running"):
        st.toast("A demo is already running.")
        return
    DEMO_STATE.parent.mkdir(exist_ok=True)
    DEMO_STATE.write_text(json.dumps({"running": True, "step": 1, "total": 10, "label": "Starting",
                                      "updated_at": time.time(), "error": None}))
    launch("demo.py")


def demo_state() -> dict:
    """What scripts/demo.py last reported, ignored once it is stale."""
    try:
        state = json.loads(DEMO_STATE.read_text())
    except (OSError, ValueError):
        return {}
    return state if time.time() - state.get("updated_at", 0) < 180 else {}


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


def policy_panel(snap: dict) -> None:
    html(views.policy(snap))
    by_id = {p["_id"]: p for p in snap["policies"]}
    for p in snap["policies"]:
        if p.get("parent") in by_id:
            with st.expander(f"What changed from v{by_id[p['parent']]['version']} to v{p['version']} ({p['status']})"):
                st.code(policy_diff(by_id[p["parent"]], p), language="diff")
    lineage = []
    for p in sorted(snap["policies"], key=lambda p: p["version"]):
        origin = "empty, from seed" if p["version"] == 0 else f"learned from {', '.join(p.get('caused_by') or ['?'])}"
        lineage.append(f"v{p['version']} ({origin}{', active' if p['status'] == 'active' else ''})")
    st.caption("Policy lineage: " + " → ".join(lineage) + ". No rule was written by hand.")


def held_panel(snap: dict) -> None:
    html(heading("Held for review"))
    held = [m for m in snap["ledger"] if m["status"] == "quarantined"]
    if not held:
        st.caption("Nothing is held.")
    for m in held:
        with st.container(border=True):
            if m.get("conflicts_with"):
                flag = badge("flagged by the Guardian", "crit")
            elif m["_id"] in snap["reviewed"]:
                flag = badge("no conflict found", "info")
            else:
                flag = badge("under review", "run")
            html(f'<b class="q-mono">{escape(m["_id"])}</b> &nbsp;{flag}<div class="q-dim" style="margin-top:2px">'
                 f'{escape(m["label"])} · written by {escape(str(m["source"].get("run_id")))}</div>')
            # Memory text and the Guardian's reason derive from ticket text: shown escaped, never as Markdown.
            html(f'<div style="margin:8px 0">{escape(m["text"])}</div>')
            for conflict in m.get("conflicts_with", []):
                html(f'<div class="q-warnbox"><b>✕ Conflicts with {escape(str(conflict["memory_id"] or "a trusted memory"))}'
                     f'</b><br>{escape(conflict["reason"])}</div>')
            release, purge = st.columns(2)
            release.button("Release", key=f"release-{m['_id']}", on_click=decide, args=(m["_id"], True), width="stretch")
            purge.button("Purge", key=f"purge-{m['_id']}", on_click=decide, args=(m["_id"], False), width="stretch")


def demo_banner() -> None:
    state = demo_state()
    if state.get("error"):
        st.error(f"The demo stopped at step {state['step']}: {state['error']}")
    elif state.get("running"):
        st.progress(state["step"] / state["total"], text=f"Demo running · step {state['step']} of {state['total']}: {state['label']}")
    elif state and time.time() - state["updated_at"] < 45:
        st.success("Demo finished. The harness wrote policy v1, held the second ticket and kept web-08 healthy; "
                   "then it wrote policy v2 after the Route 53 change and denied the DNS change for ticket 4141.")


@st.fragment(run_every="2s")
def page() -> None:
    try:
        token = views.change_token()
        if token != st.session_state.get("token") or "snap" not in st.session_state:
            st.session_state["snap"], st.session_state["token"] = views.snapshot(), token
        snap = st.session_state["snap"]
    except Exception:  # the database is briefly empty in the middle of a reset
        st.caption("Waiting for the database…")
        return
    html(views.header(snap))
    demo_banner()
    html(views.tiles(snap) + views.operation() + story(snap) + story_dns(snap))
    left, right = st.columns([3, 2], gap="large")
    with left:
        policy_panel(snap)
        html(views.servers(snap) + views.dns_records(snap))
    with right:
        held_panel(snap)
    html(views.replay(snap) + views.feed(snap))


html(CSS)
with st.sidebar:
    st.header("Run the demo")
    st.button("Run the full demo", type="primary", on_click=launch_demo, width="stretch")
    st.caption("Resets to the empty policy, then plays all six steps with pauses. About two minutes.")
    st.divider()
    st.subheader("Or step by step")
    for label, prompt in STEPS:
        st.button(label, on_click=launch, args=("run_session.py", prompt), width="stretch")
    st.button("Reset to policy v0", on_click=launch, args=("reset.py",), width="stretch")
    st.divider()
    st.caption(f"Database `{config.DB_NAME}` on the Atlas sandbox · model `{config.LLM_MODEL}` · vector search "
               f"{'on' if config.USE_VECTOR_SEARCH else 'off'} · Raindrop {'on' if config.RAINDROP_ENABLED else 'off'}")
page()
