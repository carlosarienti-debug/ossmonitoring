import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

QUEUE_FILE = Path(__file__).parent / "data" / "queue.json"
SENT_FILE = Path(__file__).parent / "data" / "sent.json"


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


def load_sent() -> set[str]:
    if not SENT_FILE.exists():
        return set()
    try:
        return set(json.loads(SENT_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def mark_sent(phones: list[str]):
    """Add phones to sent history."""
    sent = load_sent()
    sent.update(phones)
    SENT_FILE.write_text(json.dumps(list(sent), ensure_ascii=False), encoding="utf-8")


def sent_count() -> int:
    return len(load_sent())


def add_to_queue(items: list[dict]) -> tuple[int, int]:
    """Append items to queue, skipping already-sent phones.
    Returns (added, skipped_duplicates)."""
    sent = load_sent()
    current = load_queue()
    queued_phones = {item["phone"] for item in current}

    new_items = []
    skipped = 0
    for item in items:
        if item["phone"] in sent or item["phone"] in queued_phones:
            skipped += 1
        else:
            new_items.append(item)
            queued_phones.add(item["phone"])

    current.extend(new_items)
    save_queue(current)
    return len(current), skipped


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
