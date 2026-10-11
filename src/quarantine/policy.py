"""Policy: schema, loading, enforcement at the gateway, validation, tightening check."""
import copy
import time

import jsonschema

from quarantine import db, telemetry

TOOLS = ["read_ticket", "remember", "recall", "provision_server"]
ACTIONS = ["allow", "hold", "deny"]
CONDITIONS = ["run.tainted", "always"]
STATUSES = ["active", "quarantined", "purged"]
TRUSTS = ["trusted", "untrusted"]
RANK = {"allow": 0, "hold": 1, "deny": 2}


def _strings(choices: list) -> dict:
    return {"type": "array", "items": {"type": "string", "enum": choices}}


# The part of a policy an author (the Evolver) writes. Ids, version, status and
# provenance are added by the harness, never by the author.
POLICY_SCHEMA = {
    "type": "object",
    "properties": {
        "taint_sources": _strings(TOOLS),
        "tool_rules": {"type": "array", "items": {
            "type": "object",
            "properties": {"tool": {"type": "string", "enum": TOOLS},
                           "when": {"type": "string", "enum": CONDITIONS},
                           "action": {"type": "string", "enum": ACTIONS}},
            "required": ["tool", "when", "action"], "additionalProperties": False}},
        "context_policy": {
            "type": "object",
            "properties": {"recall_status": _strings(STATUSES), "recall_trust": _strings(TRUSTS)},
            "required": ["recall_status"], "additionalProperties": False},
        "rationale": {"type": "string"},
    },
    "required": ["taint_sources", "tool_rules", "context_policy", "rationale"],
    "additionalProperties": False,
}


def proposal_schema(current: dict) -> dict:
    """POLICY_SCHEMA narrowed to what a successor of `current` can say at all: 'hold' only on
    remember, and recall filters that cannot name anything the current policy already excludes.
    The model is constrained to this schema; is_tighter still makes the final decision."""
    schema = copy.deepcopy(POLICY_SCHEMA)
    rule = schema["properties"]["tool_rules"]["items"]

    def variant(tools: list, actions: list) -> dict:
        out = copy.deepcopy(rule)
        out["properties"]["tool"]["enum"], out["properties"]["action"]["enum"] = tools, actions
        return out

    schema["properties"]["tool_rules"]["items"] = {"anyOf": [
        variant(["remember"], ACTIONS), variant([t for t in TOOLS if t != "remember"], ["allow", "deny"])]}
    context = schema["properties"]["context_policy"]["properties"]
    context["recall_status"] = _strings([x for x in STATUSES if x in _recall_set(current, "recall_status", STATUSES)])
    context["recall_trust"] = _strings([x for x in TRUSTS if x in _recall_set(current, "recall_trust", TRUSTS)])
    return schema


def load_active_policy() -> dict:
    policy = db.col("policies").find_one({"status": "active"}, sort=[("version", -1)])
    if policy is None:
        raise RuntimeError("No active policy. Run scripts/reset.py.")
    return policy


def decide(policy: dict, tool: str, tainted: bool) -> str:
    """First rule for this tool whose condition holds wins; the default is allow."""
    for rule in policy.get("tool_rules", []):
        if rule["tool"] == tool and (rule["when"] == "always" or (rule["when"] == "run.tainted" and tainted)):
            return rule["action"]
    return "allow"


def safe_args(args: dict) -> dict:
    """Arguments fit for events and traces: free text is replaced by its length."""
    return {k: (f"<{len(v)} chars>" if k in ("text", "query") else v) for k, v in args.items()}


def enforce(tool: str, run_id: str, args: dict) -> str:
    """Record the call against the run and return allow, hold or deny."""
    start = time.perf_counter()
    policy = load_active_policy()
    run = db.col("runs").find_one_and_update({"_id": run_id}, {"$push": {"tools_called": tool}}, return_document=True)
    # Taint is judged against the policy in force now, so a run that read a ticket before the
    # policy changed is still tainted afterwards. Calling a taint source is itself allowed.
    tainted = bool(run) and (run.get("tainted") or bool(set(policy.get("taint_sources", [])) & set(run["tools_called"])))
    if tainted and not run.get("tainted"):
        db.col("runs").update_one({"_id": run_id}, {"$set": {"tainted": True}})
    # A call for a run the database does not know (for example one in flight across a reset) is refused.
    decision = decide(policy, tool, tainted) if run else "deny"
    db.insert_next("events", "evt", {
        "ts": db.now(), "run_id": run_id, "kind": "tool_call", "tool": tool, "decision": decision,
        "policy_version": policy["version"], "outcome": None,
        "detail": {"args": safe_args(args), "tainted": tainted}})
    ms = (time.perf_counter() - start) * 1000
    telemetry.tool_call(run_id, tool, safe_args(args), decision, ms, policy["version"], tainted)
    if decision == "hold":
        telemetry.signal(run_id, "write_held")
    elif decision == "deny":
        telemetry.signal(run_id, "call_denied")
    return decision


def validate_policy(proposal: dict) -> str | None:
    """Return None when the proposal is usable, otherwise a one-line reason."""
    try:
        jsonschema.validate(proposal, POLICY_SCHEMA)
    except jsonschema.ValidationError as exc:
        return f"schema: {exc.message} at /{'/'.join(str(p) for p in exc.absolute_path)}"
    for rule in proposal["tool_rules"]:
        if rule["action"] == "hold" and rule["tool"] != "remember":
            return f"rule on {rule['tool']}: 'hold' is only supported for 'remember'; use 'deny' or 'allow'"
    if not proposal["context_policy"]["recall_status"]:
        return "context_policy.recall_status must list at least one status"
    return None


def _recall_set(policy: dict, key: str, everything: list) -> set:
    """A missing recall filter means no restriction, which is the full set."""
    return set(policy.get("context_policy", {}).get(key, everything))


def is_tighter(old: dict, new: dict) -> bool:
    """True only if `new` restricts at least as much as `old` everywhere and differs.

    Rules are compared by the decision they produce for every tool, tainted or not,
    which is what "every old rule still exists with an action at least as strict"
    means once rule order and shadowing are taken into account.
    """
    old_taint, new_taint = set(old.get("taint_sources", [])), set(new.get("taint_sources", []))
    old_status, new_status = _recall_set(old, "recall_status", STATUSES), _recall_set(new, "recall_status", STATUSES)
    old_trust, new_trust = _recall_set(old, "recall_trust", TRUSTS), _recall_set(new, "recall_trust", TRUSTS)
    if not (new_taint >= old_taint and new_status <= old_status and new_trust <= old_trust):
        return False
    changed = (new_taint, new_status, new_trust) != (old_taint, old_status, old_trust)
    for tool in TOOLS:
        for tainted in (False, True):
            before, after = decide(old, tool, tainted), decide(new, tool, tainted)
            if RANK[after] < RANK[before]:
                return False
            changed = changed or after != before
        # A run that was clean under the old taint sources may be tainted under the new ones.
        if new_taint > old_taint and RANK[decide(new, tool, True)] < RANK[decide(old, tool, False)]:
            return False
    return changed
