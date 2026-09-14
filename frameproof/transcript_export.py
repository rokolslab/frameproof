"""Durable speech text and bounded reading/export of existing transcripts."""

import json
import math
import os
import re
import tempfile
from pathlib import Path

from .util import tc

FORMATS = {"txt": "text/plain", "md": "text/markdown", "srt": "application/x-subrip"}
MAX_BYTES = 64 * 1024 * 1024


def read_rows(folder):
    root = Path(folder).resolve()
    source = root / "segments.jsonl"
    if not source.resolve().is_relative_to(root):
        raise ValueError("Недопустимый путь расшифровки.")
    if not source.exists():
        index = root / "index.json"
        if index.exists() and index.resolve().is_relative_to(root):
            metadata = json.loads(index.read_text(encoding="utf-8"))
            if metadata.get("transcript", {}).get("segment_count", 0):
                raise ValueError(
                    "Файл расшифровки отсутствует. Проверьте папку результата."
                )
        return []
    if source.stat().st_size > MAX_BYTES:
        raise ValueError("Расшифровка больше 64 МиБ. Откройте segments.jsonl на хосте.")
    rows = []
    try:
        with source.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                start, end = float(row["t0"]), float(row["t1"])
                if (
                    not math.isfinite(start)
                    or not math.isfinite(end)
                    or not 0 <= start <= end <= 1_000_000_000
                ):
                    raise ValueError
                if not isinstance(row["text"], str):
                    raise TypeError
                rows.append(
                    {
                        "i": len(rows),
                        "t0": start,
                        "t1": end,
                        "text": row["text"],
                        "tc": tc(start),
                    }
                )
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise ValueError(
            "Файл расшифровки повреждён. Проверьте segments.jsonl на хосте."
        ) from exc
    return rows


def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def render(rows, format):
    if format not in FORMATS:
        raise ValueError("Формат: txt, md или srt.")
    if format == "txt":
        return "\n\n".join(row["text"].strip() for row in rows) + ("\n" if rows else "")
    if format == "md":
        parts = ["# Расшифровка\n"]
        for row in rows:
            text = re.sub(r"([\\`*_{}\[\]<>#!|])", r"\\\1", row["text"].strip())
            parts.append(f"## {timestamp(row['t0']).replace(',', '.')}\n\n{text}\n")
        return "\n".join(parts)
    return "\n".join(
        f"{i}\n{timestamp(row['t0'])} --> {timestamp(row['t1'])}\n{row['text'].strip()}\n"
        for i, row in enumerate(rows, 1)
    )


def _atomic_write(path, text):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Нельзя сохранять расшифровку через символическую ссылку.")
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as stream:
            name = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def save(folder, transcript):
    """Save immediately after ASR, before fallible frame extraction or OCR."""
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    rows = [
        {**segment.as_row(), "tc": tc(segment.t0)} for segment in transcript.segments
    ]
    for format in FORMATS:
        _atomic_write(root / f"transcript.{format}", render(rows, format))
    _atomic_write(
        root / "segments.jsonl",
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
    )
