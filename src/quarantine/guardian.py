"""Guardian: reviews each held (quarantined) memory write against trusted memories.

Run the watcher:  python -m quarantine.guardian   (with src on PYTHONPATH)
"""
import json
import sys

from quarantine import db, llm, memory_store, policy, telemetry

SYSTEM = (
    "You review memory writes for an IT operations team. A new write is being held. Compare it "
    "with the trusted memories. Report a conflict only when the held write contradicts a trusted "
    "memory, for example a different value for the same setting. Unrelated facts do not conflict. "
    "Give the id of the trusted memory it contradicts, and a one-sentence reason."
)

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"conflict": {"type": "boolean"},
                   "conflicting_memory_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                   "reason": {"type": "string"}},
    "required": ["conflict", "conflicting_memory_id", "reason"],
    "additionalProperties": False,
}


def _brief(memory: dict) -> dict:
    return {"id": memory["_id"], "label": memory["label"], "text": memory["text"]}


def _fallback(entry: dict, trusted: list) -> dict:
    """Without an LLM: the same label with different text is a conflict."""
    for memory in trusted:
        if memory["label"] == entry["label"] and memory["text"] != entry["text"]:
            return {"conflict": True, "conflicting_memory_id": memory["_id"],
                    "reason": f"Same label '{entry['label']}' as a trusted memory, different text."}
    return {"conflict": False, "conflicting_memory_id": None, "reason": "No trusted memory shares this label."}


def review_held_write(mem_id: str) -> dict:
    ledger = db.col("memory_ledger")
    entry = ledger.find_one({"_id": mem_id})
    trusted = memory_store.nearest_trusted(entry["text"])
    try:
        prompt = json.dumps({"held_write": _brief(entry), "trusted_memories": [_brief(m) for m in trusted]})
        verdict = llm.chat_json(prompt, VERDICT_SCHEMA, system=SYSTEM)
    except Exception as exc:
        print(f"guardian: LLM unavailable ({type(exc).__name__}), using the label fallback", file=sys.stderr)
        verdict = _fallback(entry, trusted)
    if verdict["conflicting_memory_id"] not in {m["_id"] for m in trusted}:
        verdict["conflicting_memory_id"] = None
    conflicts = ([{"memory_id": verdict["conflicting_memory_id"], "reason": verdict["reason"]}]
                 if verdict["conflict"] else [])
    run_id = entry["source"].get("run_id")
    db.insert_next("events", "evt", {
        "ts": db.now(), "run_id": run_id, "kind": "verdict", "tool": "remember", "decision": None,
        "policy_version": policy.load_active_policy()["version"], "outcome": None,
        "detail": {"memory_id": mem_id, **verdict}})
    ledger.update_one({"_id": mem_id}, {"$set": {"conflicts_with": conflicts}})
    if verdict["conflict"] and run_id:
        telemetry.signal(run_id, "guardian_conflict", negative=True)
    return verdict


def _review_once(mem_id: str) -> None:
    if db.col("events").find_one({"kind": "verdict", "detail.memory_id": mem_id}):
        return  # already reviewed (this also absorbs the echo of our own update)
    verdict = review_held_write(mem_id)
    print(f"guardian: {mem_id} conflict={verdict['conflict']} with={verdict['conflicting_memory_id']}", flush=True)


def watch() -> None:
    """Review every entry that becomes quarantined, including ones already waiting at startup."""
    match = {"$match": {"operationType": {"$in": ["insert", "update", "replace"]},
                        "fullDocument.status": "quarantined"}}
    with db.col("memory_ledger").watch([match], full_document="updateLookup") as stream:
        print("guardian: watching memory_ledger", flush=True)
        for waiting in db.col("memory_ledger").find({"status": "quarantined"}, {"_id": 1}):
            _review_once(waiting["_id"])
        for change in stream:
            _review_once(change["documentKey"]["_id"])


if __name__ == "__main__":
    try:
        watch()
    except KeyboardInterrupt:
        pass
