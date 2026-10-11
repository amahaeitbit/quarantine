"""Raindrop wrappers. Every function is a no-op unless RAINDROP_ENABLED=1.

Telemetry must never break the harness, so failures are swallowed after one warning.
"""
import sys

from quarantine import config

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
def begin(run_id: str, prompt: str, policy_version: int) -> None:
    import raindrop.analytics as raindrop
    _open[run_id] = raindrop.begin(user_id="it-ops-worker", event="worker_run", event_id=run_id,
                                   input=prompt, properties={"policy_version": policy_version})


@_guard
def finish(run_id: str, summary: str) -> None:
    import raindrop.analytics as raindrop
    interaction = _open.pop(run_id, None) or raindrop.resume_interaction(event_id=run_id)
    interaction.finish(output=summary)
    raindrop.flush()


@_guard
def tool_call(run_id: str, tool: str, safe_args: dict, decision: str, ms: float,
              policy_version: int, tainted: bool) -> None:
    import raindrop.analytics as raindrop
    raindrop.resume_interaction(event_id=run_id).track_tool(
        name=tool, input=safe_args, output={"decision": decision}, duration_ms=ms,
        properties={"policy_version": policy_version, "tainted": tainted})


@_guard
def signal(run_id: str, name: str, negative: bool = False) -> None:
    import raindrop.analytics as raindrop
    raindrop.track_signal(event_id=run_id, name=name, sentiment="NEGATIVE" if negative else None)
    raindrop.flush()
