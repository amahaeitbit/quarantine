"""Empty the seven collections and re-seed. Documents are deleted, not collections,
so indexes (including any vector search index) survive a reset."""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quarantine import config, db  # noqa: E402
from seed import seed  # noqa: E402


def reset(db_name: str | None = None) -> None:
    d = db.db(db_name)
    with ThreadPoolExecutor(max_workers=len(db.COLLECTIONS)) as pool:
        list(pool.map(lambda name: d[name].delete_many({}), db.COLLECTIONS))
    seed(db_name)


if __name__ == "__main__":
    start = time.perf_counter()
    reset()
    print(f"Reset database '{config.DB_NAME}' in {time.perf_counter() - start:.1f}s.")
