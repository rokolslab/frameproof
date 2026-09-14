"""Persistent, serialized subprocess jobs. No model lives in the HTTP process."""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psutil

from .progress import read as read_progress


class Jobs:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.process = None
        self.active = None
        self.rows = {}
        for path in self.root.glob("*/job.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                if row["state"] in ("running", "cancelling"):
                    row["state"] = "interrupted"
                self.rows[row["id"]] = row
            except (OSError, ValueError, KeyError):
                continue

    def save(self, row):
        dest = self.root / row["id"] / "job.json"
        temp = dest.with_suffix(".tmp")
        temp.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        temp.replace(dest)

    def list(self):
        with self.lock:
            return [
                dict(r)
                for r in sorted(
                    self.rows.values(), key=lambda r: r["created"], reverse=True
                )
            ]

    def start(self, args, title):
        with self.lock:
            if self.active:
                raise ValueError(
                    "Уже идёт обработка. Дождитесь завершения или остановите её."
                )
            identifier = uuid.uuid4().hex
            folder = self.root / identifier
            folder.mkdir()
            row = {
                "id": identifier,
                "title": title,
                "created": time.time(),
                "state": "running",
            }
            log = (folder / "process.log").open("wb")
            try:
                self.process = subprocess.Popen(
                    [
                        sys.executable,
                        "-u",
                        "-m",
                        "frameproof",
                        "index",
                        *args,
                        "--out",
                        str(folder / "index"),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    start_new_session=os.name != "nt",
                    env={
                        **os.environ,
                        "FRAMEPROOF_PROGRESS_FILE": str(folder / "progress.json"),
                    },
                )
            except Exception:
                log.close()
                raise
            self.active = identifier
            self.rows[identifier] = row
            self.save(row)
            threading.Thread(
                target=self.watch, args=(identifier, self.process, log), daemon=True
            ).start()
            return dict(row)

    def watch(self, identifier, process, log):
        code = process.wait()
        log.close()
        with self.lock:
            row = self.rows[identifier]
            row["state"] = (
                "cancelled"
                if row["state"] == "cancelling"
                else ("done" if code == 0 else "error")
            )
            row["exit_code"] = code
            row["finished"] = time.time()
            self.save(row)
            self.active = None
            self.process = None

    def cancel(self):
        with self.lock:
            if not self.active or self.process.poll() is not None:
                return
            self.rows[self.active]["state"] = "cancelling"
            self.save(self.rows[self.active])
            try:
                parent = psutil.Process(self.process.pid)
                parent.suspend()  # prevent another child being created during termination
                children = parent.children(recursive=True)
                for proc in children:
                    try:
                        proc.kill()
                    except psutil.NoSuchProcess:
                        pass
                parent.kill()
                psutil.wait_procs(children, timeout=5)
            except psutil.NoSuchProcess:
                pass

    def delete(self, identifier):
        """Remove a finished job and every artifact created for it.

        Source videos live outside a job folder (or in the separate uploads
        store), so this deliberately removes only ``jobs/<id>``.
        """
        with self.lock:
            row = self.rows.get(identifier)
            if row is None:
                raise ValueError("Обработка не найдена.")
            if identifier == self.active or row["state"] in ("running", "cancelling"):
                raise ValueError("Сначала остановите обработку и дождитесь её завершения.")
            folder = (self.root / identifier).resolve()
            if not folder.is_relative_to(self.root.resolve()):
                raise ValueError("Недопустимый идентификатор обработки.")
            shutil.rmtree(folder)
            del self.rows[identifier]

    def detail(self, identifier):
        with self.lock:
            row = dict(self.rows[identifier])
        row["progress"] = read_progress(
            self.root / identifier / "progress.json", row["state"]
        )
        path = self.root / identifier / "process.log"
        if path.exists():
            with path.open("rb") as fh:
                fh.seek(max(0, path.stat().st_size - 16000))
                row["log"] = fh.read().decode("utf-8", errors="replace")
        row["resources"] = (
            "Процесс обработки работает"
            if row["state"] in ("running", "cancelling")
            else "Процесс обработки завершён; модель в веб-сервере не хранится"
        )
        return row
