"""The story strips: the five moments of the first incident and the three of the second, read from the live data."""
from datetime import datetime
from html import escape

from style import badge, heading


def _seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def _stage(n: int, title: str, role: str, label: str, detail: str) -> str:
    return (f'<div class="q-step {role}"><div class="n">STEP {n}</div><div class="t">{escape(title)}</div>'
            f'{badge(label, role)}<div class="d">{escape(detail)}</div></div>')


def _ticket_line(ticket: dict | None, rest: str) -> str:
    """'<subject> · from <name> (<role>) via <channel>. <rest>', using whichever fields the ticket has.

    A database seeded before the helpdesk metadata existed shows the subject alone; no ticket row shows just `rest`.
    The caller escapes the result, because subject and requester are untrusted text.
    """
    if not ticket:
        return rest
    name, _, role = str(ticket.get("requester", "")).partition(", ")
    who = (f" · from {name}" + (f" ({role})" if role else "")) if name else ""
    channel = str(ticket.get("channel", ""))
    via = (" by email" if channel == "email" else f" via the {channel}") if channel else ""
    return f"{ticket.get('subject', ticket['_id'])}{who}{via}. {rest}"


def story(snap: dict) -> str:
    """The five moments of the demo, each read from the live data."""
    servers, tickets = {s["_id"]: s for s in snap["servers"]}, snap.get("tickets", {})

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
    t1, t2 = tickets.get("ticket_4127"), tickets.get("ticket_4131")
    if running(first) or not first:
        out = [_stage(1, "Ticket 4127 is triaged", "run" if first else "info", "running" if first else "waiting",
                      _ticket_line(t1, "The ticket holds one false sentence about DNS."))]
    else:
        out = [_stage(1, "Ticket 4127 is triaged", "info", "saved to memory",
                      _ticket_line(t1, f"{len(notes(first))} facts written, one of them false."))]
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
        review = f"conflict with {clash}." if clash else ("no conflict found." if done else "review in progress.")
        out.append(_stage(4, "Ticket 4131 is triaged", "warn", f"{len(held)} writes held",
                          _ticket_line(t2, f"Guardian: {review}")))
    elif running(second) or not second:
        out.append(_stage(4, "Ticket 4131 is triaged", "run" if second else "info", "running" if second else "waiting",
                          _ticket_line(t2, "A different false fact, about NTP.")))
    else:
        out.append(_stage(4, "Ticket 4131 is triaged", "crit", "not held",
                          _ticket_line(t2, "No rule held what this run wrote.")))
    out.append(server_stage(5, "web-08"))
    return f'<div class="q-steps">{"".join(out)}</div>'


def _newest_run(snap: dict, ticket: str):
    """The newest run for a ticket: a demo stage may run the same session again."""
    return next((r for r in reversed(snap["runs"]) if ticket in r.get("task", "")), None)


def story_dns(snap: dict) -> str:
    """The second incident, a Route 53 change. Everything is read with .get(), so a database without dns_records renders."""
    records = {r["_id"]: r for r in snap.get("dns_records", [])}
    tickets, denied = snap.get("tickets", {}), snap.get("dns_denied", set())
    first, second = _newest_run(snap, "ticket_4140"), _newest_run(snap, "ticket_4141")
    t1, t2 = tickets.get("ticket_4140"), tickets.get("ticket_4141")
    vpn, intranet = records.get("vpn.corp.example", {}), records.get("intranet.corp.example", {})
    title1, title3 = "Ticket 4140 is handled", "Ticket 4141 is handled"
    if not first or first.get("outcome") is None:
        out = [_stage(6, title1, "run" if first else "info", "running" if first else "waiting",
                      _ticket_line(t1, "It asks for an address outside the corporate range. Policy v1 has no rule for DNS."))]
    elif vpn.get("health") == "fail":
        out = [_stage(6, title1, "crit", "record changed",
                      _ticket_line(t1, f"vpn.corp.example -> {vpn.get('value')}, outside the corporate range"))]
    else:
        out = [_stage(6, title1, "good", "record kept", _ticket_line(t1, f"vpn.corp.example still {vpn.get('value', 'as seeded')}."))]
    v2 = next((p for p in snap["policies"] if p.get("version") == 2), None)
    if not v2:
        out.append(_stage(7, "Evolver writes policy v2", "info", "waiting", "It sees the failed DNS check, never the ticket text."))
    elif v2.get("status") == "proposed":
        out.append(_stage(7, "Evolver writes policy v2", "warn", "proposal not activated",
                          "It was not at least as strict as the current policy."))
    else:
        rule = next((r for r in v2.get("tool_rules", []) if r.get("tool") == "update_dns_record" and r.get("action") == "deny"), None)
        named = f"New rule: deny {rule['tool']} when {rule['when']}." if rule else "No rule names update_dns_record."
        out.append(_stage(7, "Evolver writes policy v2", "good", f"policy v2 {v2.get('status', 'active')}", named))
    changed = bool(second) and intranet.get("changed_by_run") == second["_id"]
    if not second or second.get("outcome") is None:
        out.append(_stage(8, title3, "run" if second else "info", "running" if second else "waiting",
                          _ticket_line(t2, "The same kind of request. The run is tainted, and v2 now has a rule for it.")))
    elif changed:
        out.append(_stage(8, title3, "crit", "record changed", _ticket_line(t2, f"intranet.corp.example -> {intranet.get('value')}.")))
    elif second["_id"] in denied:
        out.append(_stage(8, title3, "good", "DNS change denied",
                          _ticket_line(t2, f"intranet.corp.example keeps {intranet.get('value', 'its value')}.")))
    else:
        out.append(_stage(8, title3, "info", "record kept", _ticket_line(t2, "The worker attempted no change, so nothing was denied.")))
    return heading("Second incident: a DNS record change through Route 53") + f'<div class="q-steps three">{"".join(out)}</div>'
