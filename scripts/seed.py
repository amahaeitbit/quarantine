"""Insert the starting state: policy v0, trusted memories, demo tickets, baseline, DNS records."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pymongo import ReplaceOne  # noqa: E402

from quarantine import config, db  # noqa: E402

DATA = config.ROOT / "data"
SEED_TS = "2026-10-01T09:00:00.000+00:00"

POLICY_V0 = {
    "_id": "policy_v0", "version": 0, "parent": None, "author": "seed", "status": "active",
    "taint_sources": [], "tool_rules": [],
    "context_policy": {"recall_status": ["active"]},
    "rationale": "Empty starting policy.",
}

TRUSTED_MEMORIES = [
    ("mem_0001", "dns-resolvers", "Corporate DNS resolvers are 10.0.0.2 and 10.0.0.3."),
    ("mem_0002", "ntp-servers", "Corporate NTP servers are 10.0.0.10 and 10.0.0.11."),
]


# A records in the corporate Route 53 zone, all inside the baseline's allowed ranges.
DNS_RECORDS = [
    ("vpn.corp.example", "10.0.0.20"),
    ("mail.corp.example", "10.0.0.25"),
    ("intranet.corp.example", "10.0.0.30"),
]


def _memory(mem_id: str, label: str, text: str) -> dict:
    return {"_id": mem_id, "label": label, "text": text, "status": "active", "trust": "trusted",
            "source": {"type": "seed", "run_id": None}, "conflicts_with": [],
            "decided_by": None, "created_at": SEED_TS}


def _dns_record(name: str, value: str) -> dict:
    return {"_id": name, "zone": "corp.example", "type": "A", "value": value,
            "changed_by_run": None, "health": "pass"}


def _upsert(collection, docs: list) -> None:
    collection.bulk_write([ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs])


def seed(db_name: str | None = None) -> None:
    d = db.db(db_name)
    _upsert(d.policies, [POLICY_V0])
    _upsert(d.memory_ledger, [_memory(*m) for m in TRUSTED_MEMORIES])
    _upsert(d.tickets, json.loads((DATA / "tickets_demo.json").read_text()))
    _upsert(d.baseline, [json.loads((DATA / "baseline.json").read_text())])
    _upsert(d.dns_records, [_dns_record(*r) for r in DNS_RECORDS])
    db.ensure_indexes(db_name)


if __name__ == "__main__":
    if "--vector-index" in sys.argv:  # optional: python scripts/seed.py --vector-index
        from quarantine.memory_store import VECTOR_INDEX
        print(f"Vector index '{VECTOR_INDEX}': {db.ensure_vector_index(VECTOR_INDEX)}")
        sys.exit()
    seed()
    print(f"Seeded database '{config.DB_NAME}'.")
