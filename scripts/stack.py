"""Start and stop the local processes (gateway, Guardian, Evolver) for scripts that need them."""
import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
SERVICES = {
    "gateway": ["src/quarantine/gateway.py"],
    "guardian": ["-m", "quarantine.guardian"],
    "evolver": ["-m", "quarantine.evolver"],
}


def port_open(url: str) -> bool:
    parsed = urlparse(url)
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((parsed.hostname or "127.0.0.1", parsed.port or 8000)) == 0


def _wait(ready, what: str, log: Path, seconds: float = 30) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if ready():
            return
        time.sleep(0.2)
    tail = "\n".join(log.read_text().splitlines()[-8:]) if log.exists() else "(no log)"
    raise RuntimeError(f"{what} did not start within {seconds:g}s. Last log lines:\n{tail}")


@contextlib.contextmanager
def running(url: str, services=("gateway", "guardian", "evolver"), tag: str = ""):
    """Run the services for the duration of the block, unless a gateway is already up at `url`
    (start_all.sh), in which case that stack is used as it is."""
    if port_open(url):
        print(f"  using the stack already running at {url}")
        yield
        return
    LOGS.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUNBUFFERED": "1", "GATEWAY_URL": url}
    procs, logs = [], {}
    try:
        for name in services:
            logs[name] = LOGS / f"{name}{tag}.log"
            out = open(logs[name], "w")
            procs.append(subprocess.Popen([sys.executable, *SERVICES[name]], cwd=ROOT, env=env,
                                          stdout=out, stderr=subprocess.STDOUT))
        _wait(lambda: port_open(url), "gateway", logs["gateway"])
        for name in services:
            if name != "gateway":  # watchers print "watching" once their change stream is open
                _wait(lambda n=name: "watching" in logs[n].read_text(), name, logs[name])
        print(f"  started {', '.join(services)} (logs in logs/)")
        yield
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)
