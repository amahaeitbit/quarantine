"""Mocked external monitor: a server is healthy when its DNS and NTP match the baseline."""
from quarantine import db, policy, telemetry

FIELDS = ("dns_resolvers", "ntp_servers")


def check_server(hostname: str, run_id: str) -> str:
    server = db.col("servers").find_one({"_id": hostname})
    baseline = db.col("baseline").find_one({"_id": "baseline"})
    mismatched = [f for f in FIELDS if sorted(server.get(f, [])) != sorted(baseline[f])]
    outcome = "fail" if mismatched else "pass"
    db.col("servers").update_one({"_id": hostname}, {"$set": {"health": outcome}})
    db.insert_next("events", "evt", {
        "ts": db.now(), "run_id": run_id, "kind": "health_check", "tool": "provision_server",
        "decision": None, "policy_version": policy.load_active_policy()["version"],
        "outcome": outcome, "detail": {"hostname": hostname, "mismatched": mismatched}})
    if outcome == "fail":
        telemetry.signal(run_id, "health_check_failed", negative=True)
    return outcome
