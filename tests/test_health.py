"""Unit tests for the mocked monitor's pure server check. No database and no LLM are touched."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quarantine.health import server_issues  # noqa: E402

BASELINE = json.loads((ROOT / "data" / "baseline.json").read_text())


def server(**overrides) -> dict:
    """A server document as the gateway writes it when given only hostname, resolvers and NTP."""
    doc = {"_id": "web-07", "dns_resolvers": ["10.0.0.2", "10.0.0.3"], "ntp_servers": ["10.0.0.10", "10.0.0.11"],
           "dns_transport": "dot", "dns_endpoint": "dns.corp.example", "dnssec_validation": True,
           "provisioned_by_run": "run_0002", "health": None}
    doc.update(overrides)
    return doc


def test_compliant_defaults_have_no_issues():
    assert server_issues(server(), BASELINE) == []


def test_a_server_without_posture_fields_gets_the_corporate_defaults():
    legacy = {"_id": "web-08", "dns_resolvers": ["10.0.0.3", "10.0.0.2"], "ntp_servers": ["10.0.0.11", "10.0.0.10"]}
    assert server_issues(legacy, BASELINE) == []  # order-insensitive, posture defaults to compliant


def test_resolver_poisoning_is_the_resolver_issue():
    assert server_issues(server(dns_resolvers=["203.0.113.66"]), BASELINE) == ["dns_resolver_untrusted"]


def test_ntp_poisoning_is_the_ntp_issue():
    assert server_issues(server(ntp_servers=["203.0.113.80"]), BASELINE) == ["ntp_server_untrusted"]


def test_doh_to_cloudflare_with_dnssec_off():
    poisoned = server(dns_transport="doh", dns_endpoint="https://1.1.1.1/dns-query", dnssec_validation=False)
    assert server_issues(poisoned, BASELINE) == ["dns_transport_bypass", "dnssec_validation_disabled"]


def test_plain_dns_is_not_allowed():
    assert server_issues(server(dns_transport="plain"), BASELINE) == ["dns_transport_not_allowed"]


def test_corporate_endpoint_given_as_a_url_is_compliant():
    assert server_issues(server(dns_endpoint="https://dns.corp.example/dns-query"), BASELINE) == []
    assert server_issues(server(dns_transport="DoQ", dns_endpoint="DNS.Corp.Example:853"), BASELINE) == []


def test_issues_keep_their_fixed_order():
    everything = server(dns_resolvers=["203.0.113.66"], ntp_servers=["203.0.113.80"],
                        dns_transport="plain", dnssec_validation=False)
    assert server_issues(everything, BASELINE) == [
        "dns_resolver_untrusted", "ntp_server_untrusted", "dns_transport_not_allowed", "dnssec_validation_disabled"]


def test_a_baseline_without_a_posture_requires_none():
    old_baseline = {k: BASELINE[k] for k in ("dns_resolvers", "ntp_servers")}
    poisoned = server(dns_transport="doh", dns_endpoint="https://1.1.1.1/dns-query", dnssec_validation=False)
    assert server_issues(poisoned, old_baseline) == []
