"""Optional worker progress, separate from human logs and model output."""

import json
import os
import time
from pathlib import Path


def report(stage, completed=None, total=None):
    target = os.environ.get("FRAMEPROOF_PROGRESS_FILE")
    if not target:
        return
    value = {
        "stage": stage,
        "updated": time.time(),
        "completed": completed,
        "total": total,
    }
    path = Path(target)
    try:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass  # Progress must never break indexing (disk full, locked file, etc.).


def realtime_factor(audio_seconds, elapsed_seconds):
    """How many seconds of audio were recognized per wall-clock second."""
    if not all(isinstance(value, (int, float)) and value > 0 for value in (audio_seconds, elapsed_seconds)):
        return None
    return round(audio_seconds / elapsed_seconds, 2)


def read(path, state):
    result = {"stage": "Подготовка", "percent": None, "completed": None, "total": None}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        result["stage"] = str(data["stage"])[:150]
        completed, total = data.get("completed"), data.get("total")
        if (
            isinstance(completed, (int, float))
            and isinstance(total, (int, float))
            and 0 <= completed <= total
            and total > 0
        ):
            result.update(
                completed=completed, total=total, percent=round(completed / total * 100)
            )
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if state == "done":
        result.update(stage="Обработка завершена", percent=100)
    elif state in ("error", "cancelled", "interrupted", "cancelling"):
        result["stage"] = {
            "error": "Ошибка обработки",
            "cancelled": "Обработка остановлена",
            "interrupted": "Обработка прервана",
            "cancelling": "Остановка обработки",
        }[state]
        result["percent"] = None
    return result
