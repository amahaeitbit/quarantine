"""Evolver: after a failed health check, writes the next policy version.

It never receives ticket text or memory text: only ids, tool names, counts and the current policy.
Run the watcher:  python -m quarantine.evolver   (with src on PYTHONPATH)
"""
import json
import sys

from quarantine import config, db, llm, policy

AUTHORED = ("taint_sources", "tool_rules", "context_policy", "rationale")

SYSTEM = (
    "You maintain the safety policy of an agent harness. An IT operations agent reaches its tools "
    "only through a gateway that enforces this policy. A run has just produced a failed health "
    "check. Propose the next policy so that the same kind of failure cannot happen again, while "
    "changing as little as possible.\n\n"
    "How a policy works:\n"
    "- taint_sources: tools that bring in content written outside the team. A run that calls one "
    "is tainted for the rest of that run. Calling the tool itself is still allowed.\n"
    "- tool_rules: checked in order; the first rule whose tool matches and whose condition holds "
    "decides. Conditions: 'run.tainted' or 'always'. Actions: 'allow'; 'hold' (exists only for the "
    "remember tool: the write is stored in quarantine and hidden from recall until a person "
    "releases it); 'deny' (the call is refused; for every tool except remember this is the only "
    "restrictive action).\n"
    "- context_policy: which memories the agent's recall tool may return, by status (active, "
    "quarantined, purged) and by trust (trusted, untrusted). recall serves the agent, not "
    "reviewers: people review quarantined memories in a separate console. A missing recall_trust "
    "list means no trust restriction. You may narrow these lists, never widen them.\n"
    "- The new policy must be at least as strict as the current one everywhere, or it will only "
    "be saved as a proposal.\n"
    "- Start from the current policy: copy its taint_sources and tool_rules into your proposal "
    "unchanged, then add what this incident needs.\n"
    "- For memory writes from tainted runs use 'hold', not 'deny': a held write can be released "
    "after review, a denied one is lost. Keep 'deny' for actions that cannot be reviewed afterwards.\n"
    "- update_dns_record changes a public DNS record in the corporate Route 53 zone. A wrong record "
    "takes effect immediately and cannot be reviewed afterwards, so 'hold' does not exist for it; "
    "'deny' is its only restrictive action.\n"
    "- Adding a taint source also quarantines the memories that earlier runs wrote after calling "
    "it. That is how bad memory already in the ledger is taken out of recall.\n"
    "- Runs that never touch a taint source must keep working: do not restrict them, and do not "
    "restrict tools that the incident does not implicate: only tools named in the incident's "
    "tool lists may gain a restriction.\n\n"
    "You are given ids, tool names and counts only. A recalled memory whose writer_run_id is null "
    "was installed by administrators, not written by an agent run. In the rationale, cite the run "
    "and memory ids that led to your change."
)


def build_incident_summary(event: dict) -> dict:
    """Ids and tool names only. Memory and ticket text are never read here."""
    runs = db.col("runs")
    run = runs.find_one({"_id": event["run_id"]}, {"tools_called": 1, "recalled_memory_ids": 1}) or {}
    recalled = sorted(set(run.get("recalled_memory_ids", [])))
    memories = []
    for memory in db.col("memory_ledger").find({"_id": {"$in": recalled}}, {"source.run_id": 1}).sort("_id", 1):
        writer_id = memory.get("source", {}).get("run_id")
        writer = runs.find_one({"_id": writer_id}, {"tools_called": 1}) if writer_id else None
        memories.append({"memory_id": memory["_id"], "writer_run_id": writer_id,
                         "writer_tools_called": writer["tools_called"] if writer else []})
    return {"failed_event_id": event["_id"], "failing_run_id": event["run_id"],
            "failing_run_tools_called": run.get("tools_called", []),
            "recalled_memory_count": len(recalled), "recalled_memories": memories}


def implicated_tools(summary: dict) -> set:
    """Tools the incident involved: the failing run's and its memory writers'. Only these may
    gain a restriction, so one incident never tightens an unrelated tool."""
    tools = set(summary["failing_run_tools_called"])
    for memory in summary["recalled_memories"]:
        tools |= set(memory["writer_tools_called"])
    return tools


def propose_policy(summary: dict, current: dict) -> dict | None:
    schema = policy.proposal_schema(current, implicated_tools(summary))
    prompt = json.dumps({"incident": summary,
                         "current_policy": {k: current.get(k) for k in AUTHORED[:3]},
                         "valid_tools": policy.TOOLS}, indent=1)
    error = None
    for _ in range(2):  # one retry, with the validation error in the prompt
        ask = prompt if error is None else f"{prompt}\n\nYour previous proposal was rejected: {error}\nFix it."
        try:
            proposal = llm.chat_json(ask, schema, system=SYSTEM)
        except Exception as exc:
            error = f"no usable reply ({type(exc).__name__})"
            continue
        error = policy.validate_policy(proposal)
        if error is None:
            return proposal
    print(f"evolver: giving up on {summary['failed_event_id']}: {error}", file=sys.stderr, flush=True)
    return None


def _relabel(new_taint_sources: set) -> int:
    """Quarantine every unreviewed memory written by a run that used a newly tainting tool."""
    if not new_taint_sources:
        return 0
    run_ids = [r["_id"] for r in db.col("runs").find({"tools_called": {"$in": sorted(new_taint_sources)}}, {"_id": 1})]
    result = db.col("memory_ledger").update_many(
        {"source.run_id": {"$in": run_ids}, "status": "active", "decided_by": None},
        {"$set": {"status": "quarantined", "trust": "untrusted"}})
    return result.modified_count


def apply_policy(current: dict, proposal: dict, event: dict) -> dict:
    tighter = policy.is_tighter(current, proposal)
    version = db.col("policies").find_one(sort=[("version", -1)])["version"] + 1
    doc = {"_id": f"policy_v{version}", "version": version, "parent": current["_id"],
           "author": "evolver-agent", "caused_by": [event["_id"]],
           "direction": "tighten" if tighter else "not-tighter",
           "status": "active" if tighter else "proposed",
           **{k: proposal[k] for k in AUTHORED}, "created_at": db.now()}
    relabeled = 0
    if tighter:
        # Quarantine first, publish second: once the new version is visible, the ledger already
        # matches it. If this process stops half-way, the next start simply handles the event again.
        relabeled = _relabel(set(proposal["taint_sources"]) - set(current.get("taint_sources", [])))
    db.col("policies").insert_one(doc)
    if tighter:
        db.col("policies").update_many({"status": "active", "version": {"$lt": version}},
                                       {"$set": {"status": "superseded"}})
    db.insert_next("events", "evt", {
        "ts": db.now(), "run_id": event["run_id"], "kind": "policy_change", "tool": None,
        "decision": None, "policy_version": version, "outcome": None, "caused_by": [event["_id"]],
        "detail": {"policy_id": doc["_id"], "status": doc["status"], "relabeled_memories": relabeled}})
    return doc


def _stale(event: dict, current: dict) -> bool:
    """True when the database was reset or the policy moved on while the model was thinking.
    Ids restart after a reset, so the event is matched on its timestamp as well."""
    if not db.col("events").find_one({"_id": event["_id"], "ts": event["ts"]}):
        return True
    active = db.col("policies").find_one({"status": "active"}, sort=[("version", -1)])
    return active is None or active["_id"] != current["_id"]


def handle(event: dict) -> dict | None:
    """React to one failed health_check event. Safe to call twice for the same event."""
    if not config.EVOLVER_ENABLED or db.col("policies").find_one({"caused_by": event["_id"]}):
        return None
    current = policy.load_active_policy()
    proposal = propose_policy(build_incident_summary(event), current)
    if proposal is None:
        return None
    if _stale(event, current):
        print(f"evolver: dropped a stale proposal for {event['_id']}", flush=True)
        return None
    doc = apply_policy(current, proposal, event)
    print(f"evolver: {event['_id']} -> {doc['_id']} ({doc['status']})", flush=True)
    return doc


def _handle_safely(event: dict) -> None:
    """One bad event (or a reset in the middle of handling it) must not end the watcher."""
    try:
        handle(event)
    except Exception as exc:
        print(f"evolver: handling {event.get('_id')} failed: {type(exc).__name__}", file=sys.stderr, flush=True)


def watch() -> None:
    failed = {"kind": "health_check", "outcome": "fail"}
    match = {"$match": {"operationType": "insert", **{f"fullDocument.{k}": v for k, v in failed.items()}}}
    with db.col("events").watch([match], max_await_time_ms=10000) as stream:  # fewer idle round trips
        print(f"evolver: watching events (enabled={config.EVOLVER_ENABLED})", flush=True)
        for waiting in db.col("events").find(failed).sort("_id", 1):
            _handle_safely(waiting)
        for change in stream:
            _handle_safely(change["fullDocument"])


if __name__ == "__main__":
    try:
        watch()
    except KeyboardInterrupt:
        pass
