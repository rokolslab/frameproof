"""Manual browser host; remote access through SSH forwarding."""

import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import index as indexes
from .installers import Installations
from .readiness import readiness
from .util import parse_tc
from .web_jobs import Jobs
from . import transcript_export

VIDEO = {
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".avi",
    ".m4v",
    ".mpeg",
    ".mpg",
    ".wmv",
    ".ts",
}
SUBS = {".srt", ".vtt", ".json3"}


def _inside_index(path, out_dir):
    return Path(path).resolve().is_relative_to(Path(out_dir).resolve())


class Application:
    def __init__(self, data, roots):
        self.data = Path(data).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.roots = [Path(r).resolve() for r in roots]
        if any(not r.is_dir() for r in self.roots):
            raise ValueError("Каждый --media-root должен быть существующей папкой.")
        self.uploads = self.data / "uploads"
        self.uploads.mkdir(exist_ok=True)
        self.jobs = Jobs(self.data / "jobs")
        self.operations_lock = threading.RLock()
        self.installations = Installations(self.data / "installation")
        self.token = secrets.token_urlsafe(32)
        self.registry_path = self.data / "indexes.json"
        self.registry_lock = threading.Lock()
        self.registry = (
            json.loads(self.registry_path.read_text("utf-8"))
            if self.registry_path.exists()
            else {}
        )

    def local(self, value, uploaded=False):
        path = Path(value).resolve()
        roots = [*self.roots, self.uploads] if uploaded else self.roots
        if not any(path.is_relative_to(r) for r in roots):
            raise ValueError(
                "Путь вне разрешённых папок. Добавьте папку флагом --media-root при запуске."
            )
        if not path.exists():
            raise ValueError("Файл или папка не найдены на хосте.")
        return path

    def index_path(self, key):
        if key in self.jobs.rows and self.jobs.rows[key]["state"] == "done":
            return self.data / "jobs" / key / "index"
        if key in self.registry:
            return self.local(self.registry[key])
        raise ValueError("Готовый индекс не найден.")

    def browse(self, value, offset=0):
        if not value:
            return {
                "path": "",
                "parent": "",
                "entries": [
                    {"name": str(r), "path": str(r), "directory": True}
                    for r in self.roots
                ],
                "more": False,
            }
        folder = self.local(value)
        if not folder.is_dir():
            raise ValueError("Выберите папку.")
        entries = []
        for p in folder.iterdir():
            if p.name.startswith(".") or p.is_symlink():
                continue
            if p.is_dir() or p.suffix.lower() in VIDEO | SUBS:
                entries.append(
                    {"name": p.name, "path": str(p), "directory": p.is_dir()}
                )
        entries.sort(key=lambda e: (not e["directory"], e["name"].casefold()))
        parent = (
            str(folder.parent)
            if any(folder.parent.is_relative_to(r) for r in self.roots)
            else ""
        )
        return {
            "path": str(folder),
            "parent": parent,
            "entries": entries[offset : offset + 100],
            "more": len(entries) > offset + 100,
        }

    def transcript_path(self, key):
        if key in self.jobs.rows:
            folder = self.data / "jobs" / key / "index"
            if not folder.resolve().is_relative_to(self.data / "jobs"):
                raise ValueError("Недопустимый путь результата.")
            return folder
        return self.index_path(key)

    def arguments(self, body, preflight=False):
        source = str(body.get("source", "host"))
        target = str(body.get("target", "")).strip()
        if source == "url":
            url = urlparse(target)
            if (
                url.scheme not in ("https", "http")
                or not url.hostname
                or url.username
                or url.password
            ):
                raise ValueError("Укажите HTTP(S)-ссылку без логина и пароля.")
            if any(
                k.lower() in ("sign", "token", "expires", "key", "password")
                for k in parse_qs(url.query)
            ):
                raise ValueError(
                    "Подписанная ссылка содержит данные доступа. Используйте CLI для этого источника."
                )
        elif source in ("host", "upload"):
            if not (preflight and source == "upload"):
                target = str(self.local(target, uploaded=source == "upload"))
                if (
                    not Path(target).is_file()
                    or Path(target).suffix.lower() not in VIDEO
                ):
                    raise ValueError("Выберите поддерживаемый видеофайл.")
        else:
            raise ValueError("Неизвестный источник.")
        args = [target]

        def number(name, default, low, high, integer=False):
            try:
                value = float(body.get(name, default))
                if (
                    not math.isfinite(value)
                    or not low <= value <= high
                    or (integer and value != int(value))
                ):
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError(f"{name}: требуется число от {low} до {high}.")
            args.extend(
                ["--" + name.replace("_", "-"), str(int(value) if integer else value)]
            )

        number("max_gap", 15, 1, 300)
        number("max_frames", 0, 0, 100000, True)
        number("width", 1280, 320, 3840, True)
        number("max_height", 1080, 240, 4320, True)
        number("ocr_width", 0, 0, 7680, True)
        if body.get("fast"):
            args.append("--fast")
        if body.get("no_cues"):
            args.append("--no-cues")
        language = str(body.get("lang", "")).strip()
        if language:
            if not re.fullmatch("[a-z]{2,3}", language):
                raise ValueError("Язык: двух- или трёхбуквенный код, например ru.")
            args.extend(["--lang", language])
        subs = str(body.get("subs", "")).strip()
        if subs:
            subfile = self.local(subs, uploaded=True)
            if not subfile.is_file() or subfile.suffix.lower() not in SUBS:
                raise ValueError("Нужны субтитры .srt, .vtt или .json3.")
            args.extend(["--subs", str(subfile)])
        speech = body.get("speech", "auto")
        if speech not in ("auto", "off"):
            raise ValueError("Неизвестный режим речи.")
        if speech == "off":
            args.append("--no-transcribe")
        for key, default, allowed in [
            ("speech_engine", "auto", ("auto", "mlx", "whisper")),
            (
                "speech_model",
                "small",
                ("tiny", "base", "small", "medium", "large-v3", "turbo"),
            ),
            ("device", "auto", ("auto", "cpu", "cuda")),
        ]:
            value = body.get(key, default)
            if value not in allowed:
                raise ValueError("Недопустимый параметр " + key)
            args.extend(["--" + key.replace("_", "-"), value])
        report = readiness()
        present = {r["id"]: r.get("ready", r["installed"]) for r in report["items"]}
        missing = [name for name in ("ffmpeg", "numpy") if not present.get(name)]
        if (
            speech != "off"
            and not subs
            and not (preflight and body.get("upload_subs"))
            and body.get("speech_engine") in ("mlx", "whisper")
            and not present.get(body["speech_engine"])
        ):
            missing.append(body["speech_engine"])
        if source == "url" and not present.get("yt_dlp"):
            missing.append("yt-dlp")
        if (
            speech != "off"
            and not subs
            and not (preflight and body.get("upload_subs"))
            and source != "url"
            and not (present.get("mlx") or present.get("whisper"))
        ):
            missing.append("движок речи (или выберите субтитры / отключите речь)")
        ocr = body.get("ocr", "off")
        available_ocr = {option["id"] for option in report.get("ocr", {}).get("options", [])}
        if ocr != "off" and ocr not in available_ocr:
            raise ValueError("Неизвестный OCR-движок.")
        if ocr != "off":
            if not present.get(ocr):
                missing.append(ocr)
            args.append("--ocr")
            if ocr in ("windows", "tesseract"):
                import shlex

                command = [
                    sys.executable,
                    str(Path(__file__).parent / "contrib" / f"ocr_{ocr}.py"),
                ]
                args.extend(
                    [
                        "--ocr-command",
                        subprocess.list2cmdline(command)
                        if os.name == "nt"
                        else shlex.join(command),
                    ]
                )
        if missing:
            raise ValueError(
                "Не установлены: " + ", ".join(missing) + ". Откройте «Готовность»."
            )
        return args


def create_server(data, roots=(), host="127.0.0.1", port=8765):
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError(
            "Удалённый доступ: SSH-туннель к 127.0.0.1. Прямой HTTP в сеть отключён."
        )
    app = Application(data, roots)
    assets = Path(__file__).parent / "assets" / "web"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(
            self, data, status=200, content_type="application/json; charset=utf-8", filename=None
        ):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            valid_hosts = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            if self.headers.get("Host") not in valid_hosts:
                self.send({"error": "Недопустимый Host."}, 403)
                return False
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.send({"error": "Запрос с другого сайта отклонён."}, 403)
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + h for h in valid_hosts}:
                self.send({"error": "Недопустимый Origin."}, 403)
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            parsed = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            try:
                path = parsed.path
                if path == "/api/install":
                    self.send(app.installations.status())
                    return
                if path in ("/", "/app.js", "/style.css"):
                    name = "index.html" if path == "/" else path[1:]
                    self.send(
                        (assets / name).read_bytes(),
                        content_type=mimetypes.guess_type(name)[0] + "; charset=utf-8",
                    )
                    return
                if path == "/api/session":
                    self.send(
                        {
                            "token": app.token,
                            "hostname": socket.gethostname(),
                            "data": str(app.data),
                            "roots": [str(r) for r in app.roots],
                        }
                    )
                    return
                if path == "/api/readiness":
                    self.send(readiness())
                    return
                if path == "/api/browse":
                    self.send(
                        app.browse(q.get("path", ""), max(0, int(q.get("offset", 0))))
                    )
                    return
                if path == "/api/jobs":
                    self.send(app.jobs.list())
                    return
                if path == "/api/job":
                    self.send(app.jobs.detail(q["id"]))
                    return
                if path == "/api/report":
                    self.send(indexes.load_index(str(app.index_path(q["id"]))))
                    return
                if path == "/api/transcript":
                    folder = app.transcript_path(q["id"])
                    rows = transcript_export.read_rows(folder)
                    format = q.get("format")
                    if format:
                        if not rows:
                            raise ValueError("Распознанного текста нет. Проверьте режим речи и журнал обработки.")
                        text = transcript_export.render(rows, format)
                        self.send(text.encode("utf-8"), content_type=transcript_export.FORMATS[format] + "; charset=utf-8", filename=f"transcript.{format}")
                    else:
                        offset = max(0, int(q.get("offset", 0)))
                        limit = min(100, max(1, int(q.get("limit", 100))))
                        self.send({"rows": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit, "folder": str(folder), "saved": bool(rows)})
                    return
                if path == "/api/search":
                    folder = str(app.index_path(q["id"]))
                    term = q.get("q", "").strip()[:500]
                    limit = min(200, max(1, int(q.get("limit", 20))))
                    hits = indexes.search(folder, term, limit=limit + 1) if term else []
                    self.send(
                        {
                            "hits": [asdict(h) for h in hits[:limit]],
                            "more": len(hits) > limit,
                            "gaps": indexes.gaps_near_hits(
                                indexes.load_index(folder), hits
                            )["near"],
                        }
                    )
                    return
                if path == "/api/frames":
                    folder = str(app.index_path(q["id"]))
                    moment = parse_tc(q.get("at", "0"))
                    if not math.isfinite(moment):
                        raise ValueError("Недопустимый тайм-код.")
                    self.send(
                        indexes.frames_near(
                            folder, moment, count=min(8, max(1, int(q.get("count", 3))))
                        )
                    )
                    return
                if path == "/frame":
                    folder = app.index_path(q["id"])
                    rows = indexes.frames_by_ids(str(folder), [q["frame"]])
                    if not rows:
                        raise ValueError("Кадр не найден.")
                    file = (folder / rows[0]["path"]).resolve()
                    if not file.is_relative_to(
                        folder.resolve()
                    ) or file.suffix.lower() not in (".jpg", ".png", ".jpeg"):
                        raise ValueError("Недопустимый путь кадра.")
                    content = file.read_bytes()
                    from .__main__ import _log_served

                    _log_served(str(folder), rows)
                    self.send(content, content_type=mimetypes.guess_type(str(file))[0])
                    return
                self.send({"error": "Не найдено."}, 404)
            except (ValueError, KeyError, OSError) as exc:
                self.send({"error": str(exc)}, 400)

        def do_POST(self):
            if not self.authorized():
                return
            if not secrets.compare_digest(
                self.headers.get("X-Frameproof-Token", ""), app.token
            ):
                self.send({"error": "Сессия устарела. Обновите страницу."}, 403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                path = urlparse(self.path).path
                if path == "/api/upload":
                    q = parse_qs(urlparse(self.path).query)
                    name = Path(q.get("name", [""])[0].replace("\\", "/")).name
                    ext = Path(name).suffix.lower()
                    if ext not in VIDEO | SUBS or not 0 < size <= 20 * 1024**3:
                        raise ValueError(
                            "Неподдерживаемый или пустой файл. Максимум 20 ГиБ."
                        )
                    if size + 100 * 1024**2 > shutil.disk_usage(app.uploads).free:
                        raise ValueError("На хосте недостаточно свободного места.")
                    folder = app.uploads / secrets.token_hex(16)
                    folder.mkdir()
                    dest = folder / ("source" + ext)
                    self.connection.settimeout(60)
                    try:
                        with dest.open("xb") as fh:
                            remaining = size
                            while remaining:
                                chunk = self.rfile.read(min(1024 * 1024, remaining))
                                if not chunk:
                                    raise ValueError(
                                        "Передача прервана. Повторите загрузку."
                                    )
                                fh.write(chunk)
                                remaining -= len(chunk)
                    except Exception:
                        dest.unlink(missing_ok=True)
                        folder.rmdir()
                        raise
                    self.send({"path": str(dest), "name": name, "size": size})
                    return
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("Недопустимый размер запроса.")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise TypeError("Ожидается объект настроек.")
                if path == "/api/preflight":
                    if app.installations.active:
                        raise ValueError("Дождитесь завершения установки компонентов.")
                    app.arguments(body, preflight=True)
                    self.send({"ok": True})
                    return
                if path == "/api/index":
                    args = app.arguments(body)
                    with app.operations_lock:
                        if app.installations.active:
                            raise ValueError(
                                "Дождитесь завершения установки компонентов."
                            )
                        self.send(
                            app.jobs.start(
                                args, str(body.get("name") or Path(args[0]).name)[:200]
                            ),
                            202,
                        )
                    return
                if path == "/api/install":
                    if (
                        set(body) != {"component", "request_id", "confirmed"}
                        or body["confirmed"] is not True
                    ):
                        raise ValueError(
                            "Требуется подтверждение установки; произвольные команды запрещены."
                        )
                    with app.operations_lock:
                        if app.jobs.active:
                            raise ValueError("Сначала завершите обработку видео.")
                        self.send(
                            app.installations.start(
                                body["component"], body["request_id"]
                            ),
                            202,
                        )
                    return
                if path == "/api/open":
                    folder = app.local(body["path"])
                    indexes.load_index(str(folder))
                    if not (folder / "frames.jsonl").is_file():
                        raise ValueError("В индексе нет frames.jsonl.")
                    with app.registry_lock:
                        key = "external_" + secrets.token_hex(12)
                        app.registry[key] = str(folder)
                        tmp = app.registry_path.with_suffix(".tmp")
                        tmp.write_text(json.dumps(app.registry), encoding="utf-8")
                        tmp.replace(app.registry_path)
                    self.send({"id": key})
                    return
                if path == "/api/cancel":
                    app.jobs.cancel()
                    self.send({"ok": True})
                    return
                if path == "/api/delete-job":
                    identifier = body.get("id")
                    if not isinstance(identifier, str):
                        raise ValueError("Укажите обработку для удаления.")
                    app.jobs.delete(identifier)
                    self.send({"ok": True})
                    return
                if path == "/api/verify":
                    from .verify import audit

                    claims = audit(
                        str(body.get("text", ""))[:200000],
                        str(app.index_path(body["id"])),
                    )
                    self.send(
                        [
                            {
                                "n": c.n,
                                "text": c.text,
                                "severity": c.severity,
                                "findings": [asdict(f) for f in c.findings],
                            }
                            for c in claims
                        ]
                    )
                    return
                if path == "/api/shutdown":
                    with app.operations_lock:
                        if app.jobs.active or app.installations.active:
                            raise ValueError(
                                "Сначала дождитесь установки или остановите обработку видео."
                            )
                        self.send({"ok": True})
                        threading.Thread(
                            target=self.server.shutdown, daemon=True
                        ).start()
                    return
                self.send({"error": "Не найдено."}, 404)
            except (ValueError, TypeError, KeyError, OSError) as exc:
                self.send({"error": str(exc)}, 400)

    server = ThreadingHTTPServer((host, port), Handler)
    server.app = app
    return server


def serve(*, host="127.0.0.1", port=8765, open_browser=True, data=None, roots=()):
    server = create_server(data or Path.home() / ".frameproof-web", roots, host, port)
    url = f"http://127.0.0.1:{server.server_port}"
    print(
        f"frameproof: {url}\nДанные: {server.app.data}\nОстановка: Ctrl+C. Удалённый доступ: SSH-туннель."
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.app.jobs.cancel()
        server.server_close()
