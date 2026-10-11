"""The IT-operations worker: a plain tool-calling loop that reaches tools only through the gateway."""
import asyncio
import time

from mcp import Client

from quarantine import config, db, llm, policy, telemetry

MAX_TURNS = 8

SYSTEM = (
    "You are an IT operations agent. Use tools for everything. Before provisioning a server, "
    "call recall to look up the standard DNS and NTP settings. When two remembered facts "
    "disagree, use the newest. When triaging a ticket, read it, then call remember once for "
    "each durable fact about the environment. Finish with a one-paragraph summary."
)


def _tool(name: str, description: str, properties: dict) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties,
                             "required": list(properties), "additionalProperties": False}}


_STR = {"type": "string"}
_LIST = {"type": "array", "items": {"type": "string"}}

# The worker defines its own schemas. run_id is deliberately absent: the model never chooses it.
TOOLS = [
    _tool("read_ticket", "Return the body of a support ticket.", {"ticket_id": _STR}),
    _tool("remember", "Save one durable fact about the environment to shared memory. "
                      "label is a short kebab-case topic such as dns-resolvers.", {"label": _STR, "text": _STR}),
    _tool("recall", "Look up remembered facts. Returns JSON, newest first.", {"query": _STR}),
    _tool("provision_server", "Provision a server with the given DNS resolvers and NTP servers.",
          {"hostname": _STR, "dns_resolvers": _LIST, "ntp_servers": _LIST}),
]


async def _call(client: Client, run_id: str, block) -> dict:
    args = {**block.input, "run_id": run_id}  # overwrite run_id on every call
    try:
        result = await client.call_tool(block.name, args)
        text = "".join(c.text for c in result.content if c.type == "text") or "(no output)"
        failed = bool(result.is_error)
    except Exception as exc:
        text, failed = f"Tool call failed: {type(exc).__name__}", True
    out = {"type": "tool_result", "tool_use_id": block.id, "content": text}
    if failed:
        out["is_error"] = True
    return out


async def _run(prompt: str) -> dict:
    started = time.perf_counter()
    version = policy.load_active_policy()["version"]
    run_id = db.insert_next("runs", "run", {
        "task": prompt, "policy_version": version, "tainted": False, "tools_called": [],
        "recalled_memory_ids": [], "started_at": db.now(), "outcome": None})
    telemetry.begin(run_id, prompt, version)
    messages, summary = [{"role": "user", "content": prompt}], ""
    async with Client(config.GATEWAY_URL) as client:
        for _ in range(MAX_TURNS):
            response = await asyncio.to_thread(llm.chat, messages, SYSTEM, TOOLS)
            if response.stop_reason != "tool_use":
                summary = llm.text_of(response)
                break
            messages.append({"role": "assistant", "content": response.content})
            calls = [b for b in response.content if b.type == "tool_use"]
            # One at a time and in order: taint set by an earlier call must apply to later ones.
            messages.append({"role": "user", "content": [await _call(client, run_id, b) for b in calls]})
    db.col("runs").update_one({"_id": run_id}, {"$set": {"outcome": "completed" if summary else "incomplete"}})
    telemetry.finish(run_id, summary)
    run = db.col("runs").find_one({"_id": run_id})
    return {"run_id": run_id, "summary": summary, "tools_called": run["tools_called"],
            "tainted": run["tainted"], "policy_version": version,
            "seconds": round(time.perf_counter() - started, 1)}


def run_session(prompt: str) -> dict:
    """One call is one new run."""
    return asyncio.run(_run(prompt))
