import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

QUEUE_FILE = Path(__file__).parent / "data" / "queue.json"


def load_queue() -> list[dict]:
    if not QUEUE_FILE.exists():
        return []
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        log.error("Erro ao ler fila")
        return []


def save_queue(items: list[dict]):
    QUEUE_FILE.parent.mkdir(exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def add_to_queue(items: list[dict]) -> int:
    """Append items to queue. Returns new total."""
    current = load_queue()
    current.extend(items)
    save_queue(current)
    return len(current)


def pop_batch(n: int) -> tuple[list[dict], int]:
    """Remove and return first n items. Returns (batch, remaining_count)."""
    current = load_queue()
    batch = current[:n]
    remaining = current[n:]
    save_queue(remaining)
    return batch, len(remaining)


def queue_size() -> int:
    return len(load_queue())


def clear_queue():
    save_queue([])
