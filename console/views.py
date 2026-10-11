"""Read one snapshot of the database and turn it into the console's HTML sections."""
import json
from datetime import datetime
from html import escape

from quarantine import config, db
from style import badge, chip, decision, heading, meter_row, tile

REPLAY = config.ROOT / "data" / "replay_results.json"


def _seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def snapshot() -> dict:
    d = db.db()
    policies = list(d.policies.find().sort("version", -1))
    active = next((p for p in policies if p["status"] == "active"), policies[-1])

    def cause_of(p):
        return d.events.find_one({"_id": p["caused_by"][0]}) if p and p.get("caused_by") else None

    # The Evolver policy the story strip talks about: the active one, else its newest proposal.
    written = [p for p in policies if p["author"] == "evolver-agent"]
    evolved = next((p for p in written if p["status"] == "active"), written[0] if written else None)
    counts = d.events.aggregate([{"$match": {"kind": "tool_call"}}, {"$group": {"_id": "$decision", "n": {"$sum": 1}}}])
    return {"policies": policies, "active": active, "cause": cause_of(active), "evolved": evolved,
            "evolved_cause": cause_of(evolved),
            "change": d.events.find_one({"kind": "policy_change", "detail.policy_id": evolved["_id"]}) if evolved else None,
            "reviewed": {e["detail"]["memory_id"] for e in d.events.find({"kind": "verdict"}, {"detail.memory_id": 1})},
            "ledger": list(d.memory_ledger.find().sort("_id", 1)), "servers": list(d.servers.find().sort("_id", 1)),
            "runs": list(d.runs.find().sort("_id", 1)), "events": list(d.events.find().sort("_id", -1).limit(60)),
            "decisions": {c["_id"]: c["n"] for c in counts}, "baseline": d.baseline.find_one({"_id": "baseline"}) or {},
            "replay": json.loads(REPLAY.read_text()) if REPLAY.exists() else None}


def header(snap: dict) -> str:
    hero = ""
    if snap["replay"]:
        before, after = snap["replay"]["results"][0], snap["replay"]["results"][-1]
        hero = (f'<div class="q-hero"><div class="num">{before["poisoned_reached_server"]} → '
                f'{after["poisoned_reached_server"]}</div><div class="cap">poisoned settings that reached a server'
                f'<br>replay of {before["tickets"]} tickets, policy v{before["policy_version"]} → '
                f'v{after["policy_version"]}</div></div>')
    return ('<div class="q-head"><div><div class="q-title">Quarantine</div><div class="q-tag">A self-improving '
            'agent harness. Every tool call passes one MCP gateway, and after a failure the harness writes its own '
            f'next policy.</div></div>{hero}</div>')


def tiles(snap: dict) -> str:
    active, dec = snap["active"], snap["decisions"]
    held = [m for m in snap["ledger"] if m["status"] == "quarantined"]
    healthy = sum(s.get("health") == "pass" for s in snap["servers"])
    return ('<div class="q-tiles">'
            + tile("Active policy", f"v{active['version']}", f"written by {active['author']}")
            + tile("Gateway decisions", sum(dec.values()),
                   f"{dec.get('allow', 0)} allow · {dec.get('hold', 0)} hold · {dec.get('deny', 0)} deny")
            + tile("Held for review", len(held), f"{sum(bool(m['conflicts_with']) for m in held)} flagged by the Guardian")
            + tile("Servers healthy", f"{healthy} of {len(snap['servers'])}", "checked against the baseline")
            + '</div>')


def _stage(n: int, title: str, role: str, label: str, detail: str) -> str:
    return (f'<div class="q-step {role}"><div class="n">STEP {n}</div><div class="t">{escape(title)}</div>'
            f'{badge(label, role)}<div class="d">{escape(detail)}</div></div>')


def story(snap: dict) -> str:
    """The five moments of the demo, each read from the live data."""
    servers = {s["_id"]: s for s in snap["servers"]}

    def run_for(ticket: str):
        return next((r for r in snap["runs"] if ticket in r["task"]), None)

    def notes(run):
        return [m for m in snap["ledger"] if run and m["source"].get("run_id") == run["_id"]]

    def server_stage(n: int, name: str) -> str:
        server = servers.get(name)
        if not server:
            return _stage(n, f"{name} is provisioned", "info", "waiting", "Uses whatever recall returns for DNS and NTP.")
        if not server.get("health"):
            return _stage(n, f"{name} is provisioned", "run", "checking", "The monitor is comparing it with the baseline.")
        ok = server["health"] == "pass"
        return _stage(n, f"{name} is provisioned", "good" if ok else "crit",
                      "health check passed" if ok else "health check failed", f"DNS {', '.join(server['dns_resolvers'])}")

    def running(run) -> bool:
        return bool(run) and run.get("outcome") is None

    first, second = run_for("ticket_4127"), run_for("ticket_4131")
    if running(first) or not first:
        out = [_stage(1, "Ticket 4127 is triaged", "run" if first else "info", "running" if first else "waiting",
                      "The ticket holds one false sentence about DNS.")]
    else:
        out = [_stage(1, "Ticket 4127 is triaged", "info", "saved to memory",
                      f"{len(notes(first))} facts written from the ticket, one of them false.")]
    out.append(server_stage(2, "web-07"))
    evolved = snap["evolved"]
    if evolved and evolved["status"] == "proposed":
        out.append(_stage(3, "Evolver writes the next policy", "warn", "proposal not activated",
                          "It was not at least as strict as the current policy."))
    elif evolved:
        cause, change = snap["evolved_cause"], snap["change"]
        lag = f"{_seconds(cause['ts'], evolved['created_at']):.0f}s after the failure" if cause else "at an unknown time"
        moved = change["detail"].get("relabeled_memories", 0) if change else 0
        out.append(_stage(3, "Evolver writes the next policy", "good", f"policy v{evolved['version']} active",
                          f"Published {lag}. {moved} memories quarantined."))
    else:
        out.append(_stage(3, "Evolver writes the next policy", "info", "waiting", "It sees ids and tool names, never the text."))
    held = [m for m in notes(second) if m["status"] == "quarantined" or m.get("decided_by")]
    if second and held:
        clash = next((m["conflicts_with"][0]["memory_id"] or "a trusted memory" for m in held if m["conflicts_with"]), None)
        done = all(m["_id"] in snap["reviewed"] for m in held)
        review = f"conflicts with {clash}." if clash else ("found no conflict." if done else "is reviewing.")
        out.append(_stage(4, "Ticket 4131 is triaged", "warn", f"{len(held)} writes held", f"Guardian {review}"))
    elif running(second) or not second:
        out.append(_stage(4, "Ticket 4131 is triaged", "run" if second else "info", "running" if second else "waiting",
                          "A different false fact, about NTP."))
    else:
        out.append(_stage(4, "Ticket 4131 is triaged", "crit", "not held", "No rule held what this run wrote."))
    out.append(server_stage(5, "web-08"))
    return f'<div class="q-steps">{"".join(out)}</div>'


def policy(snap: dict) -> str:
    active = snap["active"]
    taint = "".join(chip(t) for t in active["taint_sources"]) or '<span class="q-dim">none</span>'
    rules = "".join(
        f'<div class="q-rule{" dim" if r["action"] == "allow" else ""}"><span class="q-mono">{escape(r["tool"])}</span>'
        f'<span>when {escape(r["when"])}</span>{decision(r["action"])}</div>' for r in active["tool_rules"])
    context = active.get("context_policy", {})
    recall = " · ".join(f"{k.replace('recall_', '')}: {', '.join(v)}" for k, v in context.items())
    cause = ""
    if snap["cause"]:
        cause = f' · caused by {escape(snap["cause"]["_id"])}, the failed health check on {escape(snap["cause"]["detail"]["hostname"])}'
    return (f'{heading("Active policy")}<div class="q-card"><div><b>v{active["version"]}</b> '
            f'<span class="q-dim">written by {escape(active["author"])}{cause}</span></div>'
            f'<div class="q-k" style="margin-top:12px">Taint sources</div>{taint}'
            f'<div class="q-k" style="margin-top:10px">Rules, first match wins</div>'
            f'{rules or "<div class=q-dim>No rules: every call is allowed.</div>"}'
            f'<div class="q-k" style="margin-top:10px">Recall may return</div><div class="q-mono" style="font-size:13px">'
            f'{escape(recall)}</div><div class="q-quote">{escape(active["rationale"])}</div></div>')


def servers(snap: dict) -> str:
    base, cards = snap["baseline"], ""
    for s in snap["servers"]:
        values = "".join(
            f'<div class="q-k" style="margin-top:8px">{label}</div>'
            + "".join(chip(v, bad=v not in base.get(field, [])) for v in s[field])
            for label, field in (("DNS resolvers", "dns_resolvers"), ("NTP servers", "ntp_servers")))
        cards += (f'<div class="q-card"><b class="q-mono">{escape(s["_id"])}</b> &nbsp;'
                  f'{decision(s["health"]) if s.get("health") else badge("checking", "run")}'
                  f'<span class="q-dim"> &nbsp;by {escape(s["provisioned_by_run"])}</span>{values}</div>')
    return heading("Servers") + (cards or '<div class="q-dim">No servers yet.</div>')


def replay(snap: dict) -> str:
    if not snap["replay"]:
        return heading("Before and after") + '<div class="q-dim">No replay yet. Run: python scripts/replay.py</div>'
    rows = {"reached": "", "held": ""}
    for r in snap["replay"]["results"]:
        name = f"v{r['policy_version']}"
        hit, cost = r["poisoned_reached_server"], r["harmless_notes_held"]
        rows["reached"] += meter_row(name, hit, r["poisoned_tickets"],
                                     badge(f"{hit} of {r['poisoned_tickets']} reached a server", "crit" if hit else "good"))
        rows["held"] += meter_row(name, cost, r["harmless_notes"],
                                  badge(f"{cost} of {r['harmless_notes']} held", "warn" if cost else "info"))
    return (f'{heading("Before and after: replay of 20 tickets")}<div class="q-card">'
            f'<div class="q-k">Poisoned settings that reached a server</div>{rows["reached"]}'
            f'<div class="q-k" style="margin-top:14px">Harmless notes left held for review, the cost of the policy</div>'
            f'{rows["held"]}</div>')


def _line(e: dict) -> tuple:
    detail, kind = e.get("detail", {}), e["kind"]
    if kind == "tool_call":
        tainted = ' <span class="q-dim">(tainted run)</span>' if detail.get("tainted") else ""
        return f'{escape(e["run_id"])} called <span class="q-mono">{escape(e["tool"])}</span>{tainted}', decision(e["decision"])
    if kind == "health_check":
        return f'Health check on <span class="q-mono">{escape(detail["hostname"])}</span>', decision(e["outcome"])
    if kind == "verdict":
        clash = detail.get("conflict")
        return (f'Guardian reviewed {escape(detail["memory_id"])}',
                badge(f"conflicts with {detail.get('conflicting_memory_id')}" if clash else "no conflict", "crit" if clash else "good"))
    if kind == "policy_change":
        return (f'Evolver wrote {escape(detail["policy_id"])}, {detail.get("relabeled_memories", 0)} memories quarantined',
                badge(detail["status"], "good" if detail["status"] == "active" else "warn"))
    return f'A person chose to {escape(detail.get("action", "decide"))} {escape(detail.get("memory_id", ""))}', decision(e["decision"])


def feed(snap: dict) -> str:
    rows = ""
    for e in snap["events"]:
        text, mark = _line(e)
        rows += f'<div class="q-ev"><span class="q-dim q-mono">{e["ts"][11:19]}</span><span>{text}</span>{mark}</div>'
    return heading("Live gateway feed") + f'<div class="q-card q-feed">{rows or "<div class=q-dim>No events yet.</div>"}</div>'
