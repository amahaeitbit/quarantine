"""The MCP gateway: the only way the worker reaches a tool. Every call goes through policy.enforce.

Run:  python src/quarantine/gateway.py        (port taken from GATEWAY_URL)
 or:  mcp run src/quarantine/gateway.py --transport streamable-http   (port 8000)
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server import MCPServer  # noqa: E402

from quarantine import config, db, health, memory_store, policy  # noqa: E402

mcp = MCPServer("quarantine-gateway")

DENIED = "Denied by current policy."
HELD = "Held for review. Not available to recall yet."


@mcp.tool()
def read_ticket(run_id: str, ticket_id: str) -> str:
    """Return the body of a support ticket."""
    if policy.enforce("read_ticket", run_id, {"ticket_id": ticket_id}) != "allow":
        return DENIED
    ticket = db.col("tickets").find_one({"_id": ticket_id})
    return ticket["body"] if ticket else f"No ticket named {ticket_id}."


@mcp.tool()
def remember(run_id: str, label: str, text: str) -> str:
    """Save one durable fact about the environment to shared memory."""
    decision = policy.enforce("remember", run_id, {"label": label, "text": text})
    if decision == "deny":
        return DENIED
    memory_store.write(run_id, label, text, held=decision == "hold")
    return HELD if decision == "hold" else "Saved."


@mcp.tool()
def recall(run_id: str, query: str) -> str:
    """Look up remembered facts. Returns JSON, newest first."""
    if policy.enforce("recall", run_id, {"query": query}) != "allow":
        return DENIED
    context_policy = policy.load_active_policy().get("context_policy", {})
    return json.dumps(memory_store.recall(run_id, query, context_policy))


@mcp.tool()
def provision_server(run_id: str, hostname: str, dns_resolvers: list[str], ntp_servers: list[str]) -> str:
    """Provision a server with the given DNS resolvers and NTP servers."""
    args = {"hostname": hostname, "dns_resolvers": dns_resolvers, "ntp_servers": ntp_servers}
    if policy.enforce("provision_server", run_id, args) != "allow":
        return DENIED
    db.col("servers").replace_one({"_id": hostname}, {
        "_id": hostname, "dns_resolvers": dns_resolvers, "ntp_servers": ntp_servers,
        "provisioned_by_run": run_id, "health": None}, upsert=True)
    health.check_server(hostname, run_id)  # the monitor is external: the worker is not told the result
    return f"Provisioned {hostname}."


@mcp.tool()
def update_dns_record(run_id: str, name: str, value: str) -> str:
    """Point the A record of a hostname in the corporate hosted zone corp.example (Route 53) at an IPv4
    address. Only for an explicit request to repoint a hostname."""
    if policy.enforce("update_dns_record", run_id, {"name": name, "value": value}) != "allow":
        return DENIED
    db.col("dns_records").replace_one({"_id": name}, {
        "_id": name, "zone": "corp.example", "type": "A", "value": value,
        "changed_by_run": run_id, "health": None}, upsert=True)
    health.check_dns_record(name, run_id)  # as with provision_server, the worker is not told the result
    return f"Updated {name} -> {value}."


if __name__ == "__main__":
    url = urlparse(config.GATEWAY_URL)
    mcp.run("streamable-http", host=url.hostname or "127.0.0.1", port=url.port or 8000)
