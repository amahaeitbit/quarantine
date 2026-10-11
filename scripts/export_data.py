"""Export the data the harness collected to JSON files, for reading without a database client.

Usage: python scripts/export_data.py [--replay]
Writes data/export/<database>/<collection>.json for the seven collections of DB_NAME,
and with --replay the same for REPLAY_DB_NAME. Read-only on the database.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quarantine import config, db  # noqa: E402

OUT = config.ROOT / "data" / "export"


def export(db_name: str) -> dict:
    folder = OUT / db_name
    folder.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name in db.COLLECTIONS:
        docs = list(db.col(name, db_name).find().sort("_id", 1))
        (folder / f"{name}.json").write_text(json.dumps(docs, indent=1, default=str) + "\n")
        counts[name] = len(docs)
    (folder / "summary.json").write_text(json.dumps({
        "database": db_name, "exported_at": db.now(), "counts": counts,
        "active_policy": (db.col("policies", db_name).find_one({"status": "active"}, {"_id": 1, "author": 1},
                                                              sort=[("version", -1)]) or {}).get("_id"),
        "servers": {s["_id"]: s.get("health") for s in db.col("servers", db_name).find()},
    }, indent=1) + "\n")
    return counts


if __name__ == "__main__":
    for name in [config.DB_NAME] + ([config.REPLAY_DB_NAME] if "--replay" in sys.argv else []):
        counts = export(name)
        print(f"{name}: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + f"  -> data/export/{name}/")
