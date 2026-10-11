"""Raindrop wrappers. Every function is a no-op unless RAINDROP_ENABLED=1.

Telemetry must never break the harness, so failures are swallowed after one warning.
"""
import json
import re
import sys

from quarantine import config, db

_ready = False
_warned = False
_open = {}  # run_id -> Interaction started in this process


def _enabled() -> bool:
    global _ready
    if not (config.RAINDROP_ENABLED and config.RAINDROP_WRITE_KEY):
        return False
    if not _ready:
        import raindrop.analytics as raindrop
        # auto_instrument=False: automatic SDK patching costs about 9 seconds per process,
        # and every span we need is sent explicitly below.
        raindrop.init(config.RAINDROP_WRITE_KEY, tracing_enabled=True, bypass_otel_for_tools=True,
                      auto_instrument=False)
        _ready = True
    return True


def _event_id(run_id: str) -> str:
    """Raindrop event id for a run. Run ids restart after every reset, so the run's start time
    is appended: each demo run then has its own trace instead of overwriting the last one."""
    run = db.col("runs").find_one({"_id": run_id}, {"started_at": 1}) or {}
    stamp = run.get("started_at", "")[:19].translate(str.maketrans("", "", "-:"))
    return f"{run_id}-{stamp}" if stamp else run_id


def _convo_id() -> str:
    """One Raindrop conversation per demo: every run since the last reset shares it."""
    baseline = db.col("baseline").find_one({"_id": "baseline"}, {"seeded_at": 1}) or {}
    return f"demo-{baseline['seeded_at']}" if baseline.get("seeded_at") else "demo"


def _run_properties(run_id: str, prompt: str, policy_version: int) -> dict:
    """What the prompt says about the run, so Raindrop can group traces by ticket and incident."""
    props = {"policy_version": policy_version, "run_id": run_id}
    if ticket := re.search(r"ticket_\d+", prompt):
        props["ticket_id"] = ticket.group(0)
    if host := re.search(r"named (\S+)", prompt):
        props["hostname"] = host.group(1)
    if "ticket_4140" in prompt or "ticket_4141" in prompt:
        props["incident"] = "dns-record"
    elif "ticket_4150" in prompt:
        props["incident"] = "dns-posture"
    else:
        props["incident"] = "memory-poisoning"
    return props


def _sentiment(negative: bool, positive: bool) -> str | None:
    return "NEGATIVE" if negative else "POSITIVE" if positive else None


def _guard(fn):
    def wrapped(*args, **kwargs):
        global _warned
        try:
            if _enabled():
                fn(*args, **kwargs)
        except Exception as exc:
            if not _warned:
                print(f"telemetry disabled after error: {type(exc).__name__}", file=sys.stderr)
                _warned = True
    return wrapped


@_guard
def begin(run_id: str, prompt: str, policy_version: int, tools: list | None = None) -> None:
    """Start the worker_run interaction. `tools` are the worker's tool schemas."""
    import raindrop.analytics as raindrop
    _open[run_id] = raindrop.begin(user_id="it-ops-worker", event="worker_run", event_id=_event_id(run_id),
                                   input=prompt, model=config.LLM_MODEL, tools=tools, convo_id=_convo_id(),
                                   properties=_run_properties(run_id, prompt, policy_version))


@_guard
def finish(run_id: str, summary: str) -> None:
    """End the worker_run interaction, first recording how the run ended from its document."""
    import raindrop.analytics as raindrop
    interaction = _open.pop(run_id, None) or raindrop.resume_interaction(event_id=_event_id(run_id))
    run = db.col("runs").find_one({"_id": run_id}, {"tainted": 1, "tools_called": 1, "outcome": 1}) or {}
    interaction.set_properties({k: run.get(k) for k in ("tainted", "tools_called", "outcome")})
    interaction.finish(output=summary)
    raindrop.flush()


@_guard
def tool_call(run_id: str, tool: str, safe_args: dict, decision: str, ms: float,
              policy_version: int, tainted: bool) -> None:
    import raindrop.analytics as raindrop
    raindrop.resume_interaction(event_id=_event_id(run_id)).track_tool(
        name=tool, input=safe_args, output={"decision": decision}, duration_ms=ms,
        properties={"policy_version": policy_version, "tainted": tainted})


@_guard
def signal(run_id: str, name: str, negative: bool = False, positive: bool = False) -> None:
    import raindrop.analytics as raindrop
    raindrop.track_signal(event_id=_event_id(run_id), name=name, sentiment=_sentiment(negative, positive))
    raindrop.flush()


@_guard
def agent_call(agent: str, event: str, event_id: str, input: dict, output: dict,
               properties: dict | None = None, signal: str | None = None, negative: bool = False) -> None:
    """One complete interaction for a non-worker agent (Evolver, Guardian): what it was shown,
    what it decided, and a verdict signal. A verdict is either NEGATIVE or POSITIVE."""
    import raindrop.analytics as raindrop
    interaction = raindrop.begin(user_id=agent, event=event, event_id=event_id, input=json.dumps(input),
                                 model=config.LLM_MODEL, properties=properties)
    interaction.finish(output=json.dumps(output))
    if signal:
        raindrop.track_signal(event_id=event_id, name=signal, sentiment=_sentiment(negative, not negative))
    raindrop.flush()
