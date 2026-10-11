"""Mongo client, collection handles, id allocation, index setup.

All data lives in the hackathon Atlas Sandbox cluster named by MONGODB_URI.
"""
from datetime import datetime, timezone
from urllib.parse import urlparse

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from quarantine import config

COLLECTIONS = ["tickets", "memory_ledger", "runs", "events", "policies", "servers", "baseline", "dns_records"]
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal", "mongo", "mongodb"}

_client = None


def _check_uri(uri: str) -> None:
    if not uri:
        raise RuntimeError("MONGODB_URI is not set. Put the sandbox cluster URI in .env.")
    if "<db_password>" in uri or "<password>" in uri:
        raise RuntimeError("MONGODB_URI still contains the <db_password> placeholder. Replace it with the password.")
    hosts = urlparse(uri).netloc.rsplit("@", 1)[-1]
    for host in hosts.split(","):
        if host.split(":")[0].lower() in _LOCAL_HOSTS:
            raise RuntimeError("MONGODB_URI points at a local database. Only the sandbox cluster is allowed.")


def client() -> MongoClient:
    global _client
    if _client is None:
        _check_uri(config.MONGODB_URI)
        _client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=10000, appname="quarantine")
    return _client


def db(name: str | None = None):
    return client()[name or config.DB_NAME]


def col(name: str, db_name: str | None = None):
    return db(db_name)[name]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def insert_next(collection: str, prefix: str, doc: dict) -> str:
    """Insert doc with the next sequential id (run_0007, evt_0031, mem_0042)."""
    c = col(collection)
    for _ in range(20):
        last = c.find_one({"_id": {"$regex": f"^{prefix}_"}}, {"_id": 1}, sort=[("_id", -1)])
        n = int(last["_id"].rsplit("_", 1)[1]) + 1 if last else 1
        doc["_id"] = f"{prefix}_{n:04d}"
        try:
            c.insert_one(doc)
            return doc["_id"]
        except DuplicateKeyError:
            continue  # another process took this id; try the next one
    raise RuntimeError(f"could not allocate an id in {collection}")


def ensure_vector_index(name: str, db_name: str | None = None) -> str:
    """Create the autoEmbed vector index on memory_ledger.text if it is missing.

    Returns its status. Set USE_VECTOR_SEARCH=1 only once this reports READY.
    """
    from pymongo.operations import SearchIndexModel

    ledger = db(db_name).memory_ledger
    existing = list(ledger.list_search_indexes(name))
    if not existing:
        ledger.create_search_index(SearchIndexModel(name=name, type="vectorSearch", definition={"fields": [
            {"type": "autoEmbed", "modality": "text", "path": "text", "model": "voyage-4"},
            {"type": "filter", "path": "status"},
            {"type": "filter", "path": "trust"}]}))
        return "CREATED"
    return existing[0].get("status", "UNKNOWN")


def ensure_indexes(db_name: str | None = None) -> None:
    d = db(db_name)
    d.events.create_index([("ts", -1)])
    d.events.create_index([("run_id", 1)])
    d.memory_ledger.create_index([("status", 1), ("trust", 1)])
    d.policies.create_index([("status", 1), ("version", -1)])
