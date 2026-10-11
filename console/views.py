"""Read one snapshot of the database and turn it into the console's HTML sections."""
import json
from html import escape

from quarantine import config, db, evals
from style import badge, chip, decision, heading, meter_row, tile

REPLAY = config.ROOT / "data" / "replay_results.json"


def change_token() -> tuple:
    """Cheap fingerprint of the database: every change the console shows writes an event,
    and a reset empties them. One indexed query instead of a full snapshot while idle."""
    latest = db.col("events").find_one({}, {"_id": 1, "ts": 1}, sort=[("_id", -1)]) or {}
    return latest.get("_id"), latest.get("ts"), REPLAY.stat().st_mtime if REPLAY.exists() else None


def snapshot() -> dict:
    d = db.db()
    policies = list(d.policies.find().sort("version", -1))
    active = next((p for p in policies if p["status"] == "active"), policies[-1])

    def cause_of(p):
        return d.events.find_one({"_id": p["caused_by"][0]}) if p and p.get("caused_by") else None

    # The policy the first incident produced (the Evolver's lowest version): step 3 of the story
    # describes it even after a later incident has superseded it.
    written = [p for p in policies if p["author"] == "evolver-agent"]
    evolved = min(written, key=lambda p: p["version"]) if written else None
    counts = d.events.aggregate([{"$match": {"kind": "tool_call"}}, {"$group": {"_id": "$decision", "n": {"$sum": 1}}}])
    return {"policies": policies, "active": active, "cause": cause_of(active), "evolved": evolved,
            "evolved_cause": cause_of(evolved),
            "change": d.events.find_one({"kind": "policy_change", "detail.policy_id": evolved["_id"]}) if evolved else None,
            "reviewed": {e["detail"]["memory_id"] for e in d.events.find({"kind": "verdict"}, {"detail.memory_id": 1})},
            "ledger": list(d.memory_ledger.find().sort("_id", 1)), "servers": list(d.servers.find().sort("_id", 1)),
            "runs": list(d.runs.find().sort("_id", 1)), "events": list(d.events.find().sort("_id", -1).limit(60)),
            "tickets": {t["_id"]: t for t in d.tickets.find()},
            "decisions": {c["_id"]: c["n"] for c in counts}, "baseline": d.baseline.find_one({"_id": "baseline"}) or {},
            "dns_records": list(d.dns_records.find().sort("_id", 1)),
            "dns_denied": {e["run_id"] for e in d.events.find(
                {"kind": "tool_call", "tool": "update_dns_record", "decision": "deny"}, {"run_id": 1})},
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
    records = snap.get("dns_records", [])
    dns = f" · DNS records {sum(r.get('health') == 'pass' for r in records)} of {len(records)} healthy" if records else ""
    return ('<div class="q-tiles">'
            + tile("Active policy", f"v{active['version']}", f"written by {active['author']}")
            + tile("Gateway decisions", sum(dec.values()),
                   f"{dec.get('allow', 0)} allow · {dec.get('hold', 0)} hold · {dec.get('deny', 0)} deny")
            + tile("Held for review", len(held), f"{sum(bool(m['conflicts_with']) for m in held)} flagged by the Guardian")
            + tile("Servers healthy", f"{healthy} of {len(snap['servers'])}", "checked against the baseline" + dns)
            + '</div>')


def operation() -> str:
    """One compact card placing the demo in a real IT operation. Static text, so nothing here needs escaping."""
    return ('<div class="q-card q-ops"><div class="q-k">Where this sits in a real operation</div>'
            '<div><b>Untrusted input.</b> Tickets come from employees and vendors, so anything in them may be a planted '
            'instruction.</div>'
            "<div><b>One gateway.</b> It sits in front of the helpdesk, the agent's memory and the provisioning tools, "
            'so every call is checked.</div>'
            '<div><b>Mocked monitor.</b> In this build the servers are documents, and the health check compares each one '
            'with a baseline.</div></div>')


def policy(snap: dict) -> str:
    active = snap["active"]
    taint = "".join(chip(t) for t in active["taint_sources"]) or '<span class="q-dim">none</span>'
    rules = "".join(
        f'<div class="q-rule{" dim" if r["action"] == "allow" else ""}"><span class="q-mono">{escape(r["tool"])}</span>'
        f'<span>when {escape(r["when"])}</span>{decision(r["action"])}</div>' for r in active["tool_rules"])
    context = active.get("context_policy", {})
    recall = " · ".join(f"{k.replace('recall_', '')}: {', '.join(v)}" for k, v in context.items())
    cause = ""
    if snap["cause"]:  # a server check names a hostname, a DNS check names a record
        detail = snap["cause"].get("detail", {})
        cause = (f' · caused by {escape(snap["cause"]["_id"])}, the failed health check on '
                 f'{escape(str(detail.get("hostname") or detail.get("record", "")))}')
    return (f'{heading("Active policy")}<div class="q-card"><div><b>v{active["version"]}</b> '
            f'<span class="q-dim">written by {escape(active["author"])}{cause}</span></div>'
            f'<div class="q-k" style="margin-top:12px">Taint sources</div>{taint}'
            f'<div class="q-k" style="margin-top:10px">Rules, first match wins</div>'
            f'{rules or "<div class=q-dim>No rules: every call is allowed.</div>"}'
            f'<div class="q-k" style="margin-top:10px">Recall may return</div><div class="q-mono" style="font-size:13px">'
            f'{escape(recall)}</div>{eval_line(active)}<div class="q-quote">{escape(active["rationale"])}</div></div>')


def eval_line(policy_doc: dict) -> str:
    """The policy's score on the recorded traces, computed live so every version can be compared."""
    ev = evals.score(policy_doc)
    blocked, total = ev["attacks_blocked"], ev["attacks_total"]
    clean_ok = ev["clean_unaffected"] == ev["clean_total"]
    return ('<div class="q-k" style="margin-top:10px">Eval on recorded traces</div><div>'
            + badge(f"{blocked} of {total} attacks blocked", "good" if blocked == total else ("warn" if blocked else "crit"))
            + " " + badge(f"{ev['clean_unaffected']} of {ev['clean_total']} clean runs unaffected", "good" if clean_ok else "crit")
            + " " + badge(f"{ev['harmless_held']} of {ev['harmless_total']} harmless notes held", "warn" if ev["harmless_held"] else "info")
            + "</div>")


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


def dns_records(snap: dict) -> str:
    """One card per Route 53 record. Every field is read with .get(), so an older database renders too."""
    cards = ""
    for r in snap.get("dns_records", []):
        health = r.get("health")
        by = f'<span class="q-dim"> &nbsp;changed by {escape(str(r["changed_by_run"]))}</span>' if r.get("changed_by_run") else ""
        cards += (f'<div class="q-card"><b class="q-mono">{escape(str(r.get("_id", "")))}</b> &nbsp;'
                  f'{decision(health) if health else badge("unchecked", "info")}{by}'
                  f'<div class="q-k" style="margin-top:8px">{escape(str(r.get("type", "A")))} record in '
                  f'{escape(str(r.get("zone", "")))}</div>{chip(r.get("value", ""), bad=health == "fail")}</div>')
    return heading("DNS records (Route 53, mocked)") + (cards or '<div class="q-dim">No DNS records yet.</div>')


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
        if detail.get("record"):
            return f'DNS check on <span class="q-mono">{escape(str(detail["record"]))}</span>', decision(e["outcome"])
        return f'Health check on <span class="q-mono">{escape(str(detail.get("hostname", "")))}</span>', decision(e["outcome"])
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
