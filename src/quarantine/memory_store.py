"""Memory ledger: writes, recall, and the trusted neighbours the Guardian compares against.

Only the ledger backend is built. The Agent Engine mirror (milestone 7) was skipped.
"""
from quarantine import config, db

VECTOR_INDEX = "memory_text_index"
RECALL_CAP = 20
FRESH = 5  # newest eligible memories always returned, whatever the index has caught up with

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
    """Memories matching the policy filter. The ledger decides what is eligible; vector search
    only adds the semantically closest older entries."""
    ledger = db.col("memory_ledger")
    newest = [("created_at", -1), ("_id", -1)]
    if not config.USE_VECTOR_SEARCH:
        return list(ledger.find(flt).sort(newest).limit(limit))
    # The index trails writes, sometimes by more than five seconds, so the newest entries are
    # read straight from the ledger and a just-written memory is never missed. The $match
    # re-applies the policy filter to the live documents the index points at.
    fresh = list(ledger.find(flt).sort(newest).limit(FRESH))
    ranked = ledger.aggregate([
        {"$vectorSearch": {"index": VECTOR_INDEX, "path": "text", "query": query, "filter": flt,
                           "numCandidates": 50, "limit": limit}},
        {"$match": flt}])
    return list({d["_id"]: d for d in [*ranked, *fresh]}.values())


def recall(run_id: str, query: str, context_policy: dict) -> list:
    """Memories the active policy lets this run see, newest first."""
    flt = {"status": {"$in": context_policy.get("recall_status", ["active", "quarantined", "purged"])}}
    if "recall_trust" in context_policy:
        flt["trust"] = {"$in": context_policy["recall_trust"]}
    docs = sorted(_search(query, flt, RECALL_CAP), key=lambda d: (d["created_at"], d["_id"]), reverse=True)[:RECALL_CAP]
    if docs:
        db.col("runs").update_one({"_id": run_id},
                                  {"$push": {"recalled_memory_ids": {"$each": [d["_id"] for d in docs]}}})
    return [{"id": d["_id"], "label": d["label"], "text": d["text"], "created_at": d["created_at"]} for d in docs]


def nearest_trusted(text: str, limit: int = 3) -> list:
    """Trusted, active memories closest to `text` (all of them without vector search)."""
    return _search(text, {"status": "active", "trust": "trusted"}, limit if config.USE_VECTOR_SEARCH else RECALL_CAP)
