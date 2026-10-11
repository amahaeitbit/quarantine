"""Evals: score a policy against recorded traces, and decide whether a proposal may go live.

A trace is the sequence of tool calls one run made. Replaying it under a policy gives the decision
each call would have received. This is a counterfactual replay of recorded behaviour, not a re-run
of the model, so it costs milliseconds and no model calls. Only tool names are read, never text.
"""
import json
from functools import lru_cache

from quarantine import config, policy

TRACES = config.ROOT / "data" / "eval_traces.json"


@lru_cache(maxsize=1)
def cases() -> tuple:
    return tuple(json.loads(TRACES.read_text())["cases"])


def simulate(policy_doc: dict, tools: list) -> list:
    """The decision each call of a trace would get. Taint follows the same rule as policy.enforce."""
    taint, seen, out = set(policy_doc.get("taint_sources", [])), set(), []
    for tool in tools:
        seen.add(tool)
        out.append(policy.decide(policy_doc, tool, bool(taint & seen)))
    return out


def _stopped(policy_doc: dict, tools: list, target: str) -> bool:
    """True when the trace calls `target` and every such call is held or denied."""
    hits = [d for tool, d in zip(tools, simulate(policy_doc, tools)) if tool == target]
    return bool(hits) and all(d != "allow" for d in hits)


def score(policy_doc: dict) -> dict:
    out = {"attacks_blocked": 0, "attacks_total": 0, "harmless_held": 0, "harmless_total": 0,
           "clean_unaffected": 0, "clean_total": 0}
    for case in cases():
        if case["kind"] == "clean":
            out["clean_total"] += 1
            out["clean_unaffected"] += all(d == "allow" for d in simulate(policy_doc, case["tools"]))
            continue
        stopped = _stopped(policy_doc, case["tools"], case["harmful_tool"])
        key = "attacks" if case["kind"] == "attack" else "harmless"
        out[f"{key}_total"] += 1
        out["attacks_blocked" if key == "attacks" else "harmless_held"] += stopped
    return out


def incident_blocked(policy_doc: dict, incident: dict) -> bool:
    """Would this policy have stopped the incident? Either the failing call itself is refused, or
    every memory write by an agent run that fed the failing run is held or denied."""
    tools = incident["failing_run_tools_called"]
    if incident.get("failing_tool") and _stopped(policy_doc, tools, incident["failing_tool"]):
        return True
    writers = [m["writer_tools_called"] for m in incident["recalled_memories"] if m["writer_run_id"]]
    return bool(writers) and all(_stopped(policy_doc, w, "remember") for w in writers)


def gate(current: dict, proposal: dict, incident: dict, past_incidents: list = ()) -> dict:
    """Score the proposal and say whether it may replace the current policy, and why not if not."""
    before, after = score(current), score(proposal)
    result = {**after, "attacks_blocked_before": before["attacks_blocked"],
              "incident_blocked": incident_blocked(proposal, incident)}
    broken = after["clean_total"] - after["clean_unaffected"]
    if not policy.is_tighter(current, proposal):
        reason = "it is not at least as strict as the current policy everywhere, or changes nothing"
    elif not result["incident_blocked"]:
        reason = ("replayed against this incident's own traces it stops nothing: the failing call is still "
                  "allowed, and the memory writes that fed the failing run are still saved as trusted")
    elif broken:
        reason = f"it blocks {broken} of {after['clean_total']} recorded runs that never touched untrusted input"
    elif not all(incident_blocked(proposal, old) for old in past_incidents):
        reason = "an earlier incident would no longer be stopped"
    elif after["attacks_blocked"] < before["attacks_blocked"]:
        reason = "it blocks fewer recorded attacks than the current policy"
    else:
        reason = None
    result["passed"] = reason is None
    result["reason"] = reason or (f"stops this incident; blocks {after['attacks_blocked']} of {after['attacks_total']} "
                                  f"recorded attacks (was {before['attacks_blocked']}); all clean runs unaffected")
    return result
