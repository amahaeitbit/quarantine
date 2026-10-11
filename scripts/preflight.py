"""Demo readiness in one command: python scripts/preflight.py

Checks the cluster, the model, the running stack, the replay data and the tracing flag,
and prints one line per item. Exit code 1 if anything that the demo needs is missing.
"""
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quarantine import config, db, llm  # noqa: E402
from quarantine.memory_store import VECTOR_INDEX  # noqa: E402

REPLAY = config.ROOT / "data" / "replay_results.json"


def port_open(url: str) -> bool:
    parsed = urlparse(url)
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((parsed.hostname or "127.0.0.1", parsed.port or 80)) == 0


def main() -> int:
    checks, warnings = [], []
    start = time.perf_counter()
    try:
        db.client().admin.command("ping")
        checks.append((True, f"Atlas sandbox cluster reachable ({time.perf_counter() - start:.1f}s), database {config.DB_NAME}"))
    except Exception as exc:
        checks.append((False, f"Atlas cluster: {type(exc).__name__}"))
        return report(checks, warnings)
    active = db.col("policies").find_one({"status": "active"}, sort=[("version", -1)])
    checks.append((active is not None, f"active policy: {active['_id'] if active else 'none'} (press Reset before the demo)"))
    checks.append((db.col("tickets").count_documents({}) >= 5, f"{db.col('tickets').count_documents({})} demo tickets seeded"))
    idx = list(db.col("memory_ledger").list_search_indexes(VECTOR_INDEX))
    ready = bool(idx) and idx[0].get("queryable")
    if config.USE_VECTOR_SEARCH:
        checks.append((ready, f"vector index {VECTOR_INDEX}: {idx[0].get('status') if idx else 'missing'}"))
    else:
        warnings.append("vector search is off (USE_VECTOR_SEARCH=0): recall reads the ledger only")
    try:
        start = time.perf_counter()
        reply = llm.text_of(llm.chat([{"role": "user", "content": "Reply with exactly: ready"}], max_tokens=16))
        checks.append(("ready" in reply.lower(), f"model {config.LLM_MODEL} answers ({time.perf_counter() - start:.1f}s)"))
    except Exception as exc:
        checks.append((False, f"model {config.LLM_MODEL}: {type(exc).__name__}"))
    checks.append((port_open(config.GATEWAY_URL), f"gateway at {config.GATEWAY_URL}"))
    checks.append((port_open("http://localhost:8501"), "console at http://localhost:8501"))
    for name in ("guardian", "evolver"):
        log = config.ROOT / "logs" / f"{name}.log"
        up = log.exists() and "watching" in log.read_text()
        checks.append((up, f"{name} watcher (logs/{name}.log)"))
    checks.append((REPLAY.exists(), "replay results for the headline figure (data/replay_results.json)"))
    if config.RAINDROP_ENABLED and config.RAINDROP_WRITE_KEY:
        checks.append((True, "Raindrop tracing on"))
    else:
        warnings.append("Raindrop tracing is off (RAINDROP_ENABLED=0): no traces for this demo")
    return report(checks, warnings)


def report(checks: list, warnings: list) -> int:
    for ok, text in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {text}")
    for text in warnings:
        print(f"  note {text}")
    failed = [t for ok, t in checks if not ok]
    print("READY" if not failed else f"NOT READY: {len(failed)} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
