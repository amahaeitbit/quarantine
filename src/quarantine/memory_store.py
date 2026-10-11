"""Memory ledger: writes, recall, and the trusted neighbours the Guardian compares against.

Only the ledger backend is built. The Agent Engine mirror (milestone 7) was skipped.
"""
from quarantine import config, db

VECTOR_INDEX = "memory_text_index"
RECALL_CAP = 20

if config.MEMORY_BACKEND != "ledger":
    raise RuntimeError("MEMORY_BACKEND must be 'ledger'; the agent_engine mirror was not built.")


def write(run_id: str, label: str, text: str, held: bool) -> str:
    """Insert a worker memory. A held write is quarantined and untrusted until reviewed."""
    return db.insert_next("memory_ledger", "mem", {
        "label": label, "text": text,
        "status": "quarantined" if held else "active",
        "trust": "untrusted" if held else "trusted",
        "source": {"type": "worker", "run_id": run_id},
        "conflicts_with": [], "decided_by": None, "created_at": db.now()})


def _search(query: str, flt: dict, limit: int) -> list:
    ledger = db.col("memory_ledger")
    if config.USE_VECTOR_SEARCH:
        # The index lags writes by about a second, so it only ranks. The $match on the live
        # documents is what enforces the policy filter.
        return list(ledger.aggregate([
            {"$vectorSearch": {"index": VECTOR_INDEX, "path": "text", "query": query, "filter": flt,
                               "numCandidates": 50, "limit": limit}},
            {"$match": flt}]))
    return list(ledger.find(flt).sort([("created_at", -1), ("_id", -1)]).limit(limit))


def recall(run_id: str, query: str, context_policy: dict) -> list:
    """Memories the active policy lets this run see, newest first."""
    flt = {"status": {"$in": context_policy.get("recall_status", ["active", "quarantined", "purged"])}}
    if "recall_trust" in context_policy:
        flt["trust"] = {"$in": context_policy["recall_trust"]}
    docs = sorted(_search(query, flt, RECALL_CAP), key=lambda d: (d["created_at"], d["_id"]), reverse=True)
    if docs:
        db.col("runs").update_one({"_id": run_id},
                                  {"$push": {"recalled_memory_ids": {"$each": [d["_id"] for d in docs]}}})
    return [{"id": d["_id"], "label": d["label"], "text": d["text"], "created_at": d["created_at"]} for d in docs]


def nearest_trusted(text: str, limit: int = 3) -> list:
    """Trusted, active memories closest to `text` (all of them without vector search)."""
    return _search(text, {"status": "active", "trust": "trusted"}, limit if config.USE_VECTOR_SEARCH else RECALL_CAP)
