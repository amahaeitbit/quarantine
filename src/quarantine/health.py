"""Mocked external monitor: a server is healthy when its DNS and NTP settings match the baseline,
including the DNS security posture (encrypted transport to a corporate endpoint, DNSSEC validation
on), and a DNS record when it points inside one of the baseline's allowed address ranges."""
import ipaddress
from urllib.parse import urlsplit

from quarantine import db, policy, telemetry

FIELDS = ("dns_resolvers", "ntp_servers")
_FIELD_ISSUES = (("dns_resolvers", "dns_resolver_untrusted"), ("ntp_servers", "ntp_server_untrusted"))
ENCRYPTED = ("dot", "doh", "doq")


def _host(endpoint: str) -> str:
    """The bare hostname of a resolver endpoint: scheme, port and path removed, lower-cased."""
    url = endpoint if "://" in endpoint else f"//{endpoint}"
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def server_issues(server: dict, baseline: dict) -> list[str]:
    """Issue codes for a server document judged against the baseline, in a fixed order. Pure: no
    database. A server written without the DNS posture fields gets the corporate defaults, and a
    baseline without a posture requires none."""
    issues = [code for field, code in _FIELD_ISSUES
              if sorted(server.get(field, [])) != sorted(baseline.get(field, []))]
    transport = str(server.get("dns_transport", "dot") or "").strip().lower()
    allowed = baseline.get("dns_transport_allowed")
    if allowed is not None and transport not in allowed:
        issues.append("dns_transport_not_allowed")
    endpoints = baseline.get("dns_encrypted_endpoints")
    if endpoints is not None and transport in ENCRYPTED:
        endpoint = str(server.get("dns_endpoint", "dns.corp.example") or "")
        if _host(endpoint) not in {e.lower() for e in endpoints}:
            issues.append("dns_transport_bypass")
    if baseline.get("dnssec_validation_required") and server.get("dnssec_validation", True) is False:
        issues.append("dnssec_validation_disabled")
    return issues


def check_server(hostname: str, run_id: str) -> str:
    server = db.col("servers").find_one({"_id": hostname})
    baseline = db.col("baseline").find_one({"_id": "baseline"})
    issues = server_issues(server, baseline)
    mismatched = [field for field, code in _FIELD_ISSUES if code in issues]  # kept for the console
    outcome = "fail" if issues else "pass"
    db.col("servers").update_one({"_id": hostname}, {"$set": {"health": outcome}})
    db.insert_next("events", "evt", {
        "ts": db.now(), "run_id": run_id, "kind": "health_check", "tool": "provision_server",
        "decision": None, "policy_version": policy.load_active_policy()["version"],
        "outcome": outcome, "detail": {"hostname": hostname, "mismatched": mismatched, "issues": issues}})
    if outcome == "fail":
        for issue in issues:
            telemetry.signal(run_id, issue, negative=True)
        telemetry.signal(run_id, "health_check_failed", negative=True)
    else:
        telemetry.signal(run_id, "health_check_passed", positive=True)
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
        telemetry.signal(run_id, "dns_record_outside_range", negative=True)
        telemetry.signal(run_id, "health_check_failed", negative=True)
    else:
        telemetry.signal(run_id, "health_check_passed", positive=True)
    return outcome
