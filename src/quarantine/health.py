"""Mocked external monitor: a server is healthy when its DNS and NTP match the baseline, and a DNS
record when it points inside one of the baseline's allowed address ranges."""
import ipaddress

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


def _inside(value: str, cidrs: list[str]) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False  # not an address at all: wrong whatever the allowed ranges are
    return any(address in ipaddress.ip_network(cidr) for cidr in cidrs)


def check_dns_record(name: str, run_id: str) -> str:
    record = db.col("dns_records").find_one({"_id": name})
    allowed = db.col("baseline").find_one({"_id": "baseline"})["dns_allowed_cidrs"]
    outcome = "pass" if _inside(record.get("value", ""), allowed) else "fail"
    db.col("dns_records").update_one({"_id": name}, {"$set": {"health": outcome}})
    db.insert_next("events", "evt", {
        "ts": db.now(), "run_id": run_id, "kind": "health_check", "tool": "update_dns_record",
        "decision": None, "policy_version": policy.load_active_policy()["version"],
        "outcome": outcome, "detail": {"record": name, "value": record.get("value"), "allowed_cidrs": allowed}})
    if outcome == "fail":
        telemetry.signal(run_id, "health_check_failed", negative=True)
    return outcome
