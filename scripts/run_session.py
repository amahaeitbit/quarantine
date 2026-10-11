"""Run one worker session. Usage: python scripts/run_session.py "Triage ticket_4127."

The gateway must be running (scripts/start_all.sh).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quarantine import worker  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit('usage: python scripts/run_session.py "<prompt>"')
    result = worker.run_session(sys.argv[1])
    print(f"{result['run_id']}  policy v{result['policy_version']}  {result['seconds']}s  "
          f"tools: {', '.join(result['tools_called'])}")
    print(result["summary"])
