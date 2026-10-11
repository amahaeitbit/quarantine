"""Environment loading. Secrets come from .env only and are never printed or logged."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
# Real environment variables win over .env, so a script can point one process at
# another database (replay.py does this with DB_NAME).
load_dotenv(ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _flag(name: str, default: str = "0") -> bool:
    return _get(name, default) == "1"


MONGODB_URI = _get("MONGODB_URI")
DB_NAME = _get("DB_NAME", "quarantine")
REPLAY_DB_NAME = _get("REPLAY_DB_NAME", "quarantine_replay")

LLM_PROVIDER = _get("LLM_PROVIDER", "anthropic")
LLM_MODEL = _get("LLM_MODEL", "claude-haiku-4-5")
LLM_API_KEY = _get("LLM_API_KEY")
LLM_WORKSPACE_ID = _get("LLM_WORKSPACE_ID")
LLM_EFFORT = _get("LLM_EFFORT")
LLM_TEMPERATURE = _get("LLM_TEMPERATURE")

GATEWAY_URL = _get("GATEWAY_URL", "http://localhost:8000/mcp")
USE_VECTOR_SEARCH = _flag("USE_VECTOR_SEARCH")
EVOLVER_ENABLED = _flag("EVOLVER_ENABLED", "1")
RAINDROP_ENABLED = _flag("RAINDROP_ENABLED")
RAINDROP_WRITE_KEY = _get("RAINDROP_WRITE_KEY")
MEMORY_BACKEND = _get("MEMORY_BACKEND", "ledger")
AGENT_ENGINE_MEMORY_URL = _get("AGENT_ENGINE_MEMORY_URL")
