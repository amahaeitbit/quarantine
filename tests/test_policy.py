"""Unit tests for the pure policy logic. No database and no LLM are touched."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import jsonschema  # noqa: E402

from quarantine.policy import (  # noqa: E402
    decide, is_tighter, proposal_schema, safe_args, validate_policy)

V0 = {"taint_sources": [], "tool_rules": [], "context_policy": {"recall_status": ["active"]},
      "rationale": "Empty starting policy."}
V1 = json.loads((ROOT / "fixtures" / "policy_v1.json").read_text())


def variant(base: dict, **changes) -> dict:
    out = copy.deepcopy(base)
    out.update(changes)
    return out


def test_decide_defaults_to_allow():
    assert decide(V0, "remember", tainted=True) == "allow"
    assert decide(V1, "recall", tainted=True) == "allow"


def test_decide_applies_tainted_rules_only_to_tainted_runs():
    assert decide(V1, "remember", tainted=False) == "allow"
    assert decide(V1, "remember", tainted=True) == "hold"
    assert decide(V1, "provision_server", tainted=True) == "deny"


def test_decide_first_matching_rule_wins():
    policy = variant(V0, tool_rules=[{"tool": "remember", "when": "always", "action": "deny"},
                                     {"tool": "remember", "when": "run.tainted", "action": "allow"}])
    assert decide(policy, "remember", tainted=True) == "deny"


def test_fixture_is_tighter_than_v0():
    assert is_tighter(V0, V1)


def test_identical_policy_is_not_tighter():
    assert not is_tighter(V1, copy.deepcopy(V1))
    assert not is_tighter(V1, variant(V1, rationale="Only the wording changed."))


def test_removing_a_taint_source_is_not_tighter():
    assert not is_tighter(V1, variant(V1, taint_sources=[]))


def test_dropping_or_loosening_a_rule_is_not_tighter():
    assert not is_tighter(V1, variant(V1, tool_rules=V1["tool_rules"][:1]))
    loosened = [{"tool": "remember", "when": "run.tainted", "action": "allow"}, V1["tool_rules"][1]]
    assert not is_tighter(V1, variant(V1, tool_rules=loosened))


def test_stricter_action_is_tighter():
    stricter = [{"tool": "remember", "when": "run.tainted", "action": "deny"}, V1["tool_rules"][1]]
    assert is_tighter(V1, variant(V1, tool_rules=stricter))


def test_a_shadowing_allow_rule_is_not_tighter():
    shadowed = [{"tool": "remember", "when": "always", "action": "allow"}, *V1["tool_rules"]]
    assert not is_tighter(V1, variant(V1, tool_rules=shadowed))


def test_recall_filters_may_only_narrow():
    wider = variant(V1, context_policy={"recall_status": ["active", "quarantined"], "recall_trust": ["trusted"]})
    assert not is_tighter(V1, wider)
    no_trust_filter = variant(V1, context_policy={"recall_status": ["active"]})
    assert not is_tighter(V1, no_trust_filter)  # a missing recall_trust means no restriction
    assert is_tighter(V0, variant(V0, context_policy={"recall_status": ["active"], "recall_trust": ["trusted"]}))


def test_new_taint_source_cannot_loosen_clean_runs():
    old = variant(V0, tool_rules=[{"tool": "remember", "when": "always", "action": "deny"}])
    new = variant(V0, taint_sources=["read_ticket"],
                  tool_rules=[{"tool": "remember", "when": "run.tainted", "action": "allow"},
                              {"tool": "remember", "when": "always", "action": "deny"}])
    assert not is_tighter(old, new)


def test_validate_accepts_the_fixture_shape():
    authored = {k: V1[k] for k in ("taint_sources", "tool_rules", "context_policy", "rationale")}
    assert validate_policy(authored) is None


def test_validate_rejects_bad_proposals():
    good = {k: V1[k] for k in ("taint_sources", "tool_rules", "context_policy", "rationale")}
    assert "schema" in validate_policy(variant(good, taint_sources=["send_email"]))
    assert "schema" in validate_policy(variant(good, tool_rules=[{"tool": "remember", "when": "sometimes", "action": "hold"}]))
    assert "hold" in validate_policy(variant(good, tool_rules=[{"tool": "recall", "when": "always", "action": "hold"}]))
    assert "recall_status" in validate_policy(variant(good, context_policy={"recall_status": []}))
    assert "schema" in validate_policy({k: v for k, v in good.items() if k != "rationale"})


def test_safe_args_hides_free_text():
    args = safe_args({"label": "dns-resolvers", "text": "secret words", "query": "dns"})
    assert args == {"label": "dns-resolvers", "text": "<12 chars>", "query": "<3 chars>"}


def test_proposal_schema_only_admits_tightening_moves():
    good = {k: V1[k] for k in ("taint_sources", "tool_rules", "context_policy", "rationale")}
    jsonschema.validate(good, proposal_schema(V0))
    for bad in (variant(good, context_policy={"recall_status": ["active", "quarantined"]}),
                variant(good, tool_rules=[{"tool": "provision_server", "when": "run.tainted", "action": "hold"}])):
        try:
            jsonschema.validate(bad, proposal_schema(V0))
        except jsonschema.ValidationError:
            continue
        raise AssertionError("the proposal schema admitted a move that is not a tightening")
    untrusted_only = variant(good, context_policy={"recall_status": ["active"], "recall_trust": ["untrusted"]})
    try:
        jsonschema.validate(untrusted_only, proposal_schema(V1))  # V1 already limits recall to trusted
    except jsonschema.ValidationError:
        return
    raise AssertionError("the proposal schema let recall_trust widen")
