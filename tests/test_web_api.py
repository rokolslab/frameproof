"""HTTP contracts plus real local FFmpeg processing when available."""

import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from frameproof.web import create_server


@pytest.fixture
def server(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    http = create_server(tmp_path / "data", [media], port=0)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield http, media
    http.app.jobs.cancel()
    http.shutdown()
    http.server_close()
    thread.join(timeout=10)


def request(server, path, body=None, headers=None, raw=None):
    url = f"http://127.0.0.1:{server.server_port}" + path
    hdr = {"X-Frameproof-Token": server.app.token}
    hdr.update(headers or {})
    data = (
        raw
        if raw is not None
        else json.dumps(body).encode()
        if body is not None
        else None
    )
    try:
        with urlopen(Request(url, data=data, headers=hdr), timeout=20) as response:
            content = response.read()
            return response.status, json.loads(
                content
            ) if "json" in response.headers.get("Content-Type", "") else content
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_reject_non_object_request(server):
    http, _ = server
    code, data = request(http, "/api/preflight", raw=b"[]")
    assert code == 400
    assert "объект" in data["error"]


def test_all_frame_and_speech_options_reach_cli(server, monkeypatch):
    from frameproof import web

    http, media = server
    video = media / "input.mp4"
    video.touch()
    monkeypatch.setattr(
        web,
        "readiness",
        lambda: {
            "items": [
                {"id": name, "installed": True}
                for name in ("ffmpeg", "numpy", "whisper")
            ]
        },
    )
    args = http.app.arguments(
        {
            "source": "host",
            "target": str(video),
            "max_gap": 5,
            "max_frames": 42,
            "width": 640,
            "max_height": 720,
            "ocr_width": 1920,
            "fast": True,
            "no_cues": True,
            "lang": "ru",
            "speech_engine": "whisper",
            "speech_model": "tiny",
            "device": "cpu",
        }
    )
    for flag, value in [
        ("--max-gap", "5.0"),
        ("--max-frames", "42"),
        ("--width", "640"),
        ("--max-height", "720"),
        ("--ocr-width", "1920"),
        ("--lang", "ru"),
        ("--speech-engine", "whisper"),
        ("--speech-model", "tiny"),
        ("--device", "cpu"),
    ]:
        assert args[args.index(flag) + 1] == value
    assert "--fast" in args and "--no-cues" in args


def test_csrf_host_and_diagnostics(server):
    http, _ = server
    assert request(http, "/api/session")[0] == 200
    assert request(http, "/api/session", headers={"Host": "attacker.invalid"})[0] == 403
    assert (
        request(http, "/api/session", headers={"Origin": "http://evil.test"})[0] == 403
    )
    assert (
        request(http, "/api/cancel", {}, headers={"X-Frameproof-Token": ""})[0] == 403
    )
    code, data = request(http, "/api/readiness")
    assert code == 200 and any(i["id"] == "ffmpeg" for i in data["items"])
    assert "torch" not in __import__("sys").modules


def test_file_upload_and_restricted_browser(server):
    http, media = server
    (media / "a.mp4").write_bytes(b"test")
    assert (
        request(http, "/api/browse?" + urlencode({"path": media}))[1]["entries"][0][
            "name"
        ]
        == "a.mp4"
    )
    assert request(http, "/api/browse?" + urlencode({"path": media.parent}))[0] == 400
    assert request(http, "/api/upload?name=bad.exe", raw=b"bad")[0] == 400
    code, data = request(http, "/api/upload?name=..%2F..%2Fvideo.mp4", raw=b"media")
    assert code == 200
    assert Path(data["path"]).is_relative_to(http.app.uploads)
    assert Path(data["path"]).read_bytes() == b"media"
    assert request(http, "/api/upload?name=empty.mp4", raw=b"")[0] == 400


@pytest.mark.parametrize("value", [-1, 0, 301, float("nan"), float("inf"), "broken"])
def test_numeric_validation(server, value):
    http, media = server
    path = media / "a.mp4"
    path.write_bytes(b"x")
    with pytest.raises(ValueError, match="max_gap"):
        http.app.arguments({"target": str(path), "max_gap": value})


def make_index(media):
    folder = media / "existing"
    folder.mkdir()
    (folder / "frames").mkdir()
    (folder / "frames" / "f0001.jpg").write_bytes(b"jpeg")
    (folder / "index.json").write_text(
        json.dumps(
            {
                "video": {"title": "test"},
                "transcript": {"segment_count": 1},
                "frames": {"count": 1},
                "coverage": {"gaps": []},
            }
        ),
        encoding="utf-8",
    )
    (folder / "frames.jsonl").write_text(
        json.dumps(
            {
                "id": "f0001",
                "t": 1,
                "path": "frames/f0001.jpg",
                "tc": "0:01",
                "ocr": "hello world",
                "est_tokens": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (folder / "segments.jsonl").write_text(
        json.dumps({"i": 1, "t0": 1, "t1": 2, "text": "hello speech"}) + "\n",
        encoding="utf-8",
    )
    return folder


def test_existing_search_frames_and_open_log(server):
    http, media = server
    folder = make_index(media)
    code, data = request(http, "/api/open", {"path": str(folder)})
    assert code == 200
    key = data["id"]
    code, data = request(http, "/api/search?" + urlencode({"id": key, "q": "hello"}))
    assert code == 200 and len(data["hits"]) == 2
    assert not (folder / "served.jsonl").exists()
    assert (
        request(http, "/api/frames?" + urlencode({"id": key, "at": "0:01"}))[0] == 200
    )
    assert not (folder / "served.jsonl").exists()
    assert request(http, "/frame?" + urlencode({"id": key, "frame": "f0001"})) == (
        200,
        b"jpeg",
    )
    assert "f0001" in (folder / "served.jsonl").read_text()
    assert (
        request(http, "/api/frames?" + urlencode({"id": key, "at": "99:99"}))[0] == 400
    )
    assert (
        request(http, "/api/verify", {"id": key, "text": "[0:01 / f9999] nonexistent"})[
            0
        ]
        == 200
    )


def test_frame_traversal_blocked(server):
    http, media = server
    folder = make_index(media)
    key = request(http, "/api/open", {"path": str(folder)})[1]["id"]
    (folder / "frames.jsonl").write_text(
        json.dumps({"id": "f0001", "t": 1, "path": "../../outside.jpg"}) + "\n"
    )
    assert request(http, "/frame?" + urlencode({"id": key, "frame": "f0001"}))[0] == 400


def wait_job(http, key):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        row = request(http, "/api/job?" + urlencode({"id": key}))[1]
        if row["state"] not in ("running", "cancelling"):
            return row
        time.sleep(0.1)
    pytest.fail("Worker did not exit")


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="FFmpeg integration requires binaries",
)
def test_real_video_subtitles_search_and_release(server):
    http, media = server
    video = media / "sample.mp4"
    subs = media / "sample.srt"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=5",
            "-t",
            "3",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    subs.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nSynthetic speech test\n", encoding="utf-8"
    )
    code, data = request(
        http,
        "/api/index",
        {"source": "host", "target": str(video), "subs": str(subs), "speech": "off"},
    )
    assert code == 202, data
    row = wait_job(http, data["id"])
    assert row["state"] == "done", row.get("log")
    assert row["progress"]["percent"] == 100
    progress_file = http.app.data / "jobs" / data["id"] / "progress.json"
    assert json.loads(progress_file.read_text("utf-8"))["stage"] == "Формирование отчёта"
    assert http.app.jobs.process is None
    assert request(
        http, "/api/search?" + urlencode({"id": data["id"], "q": "Synthetic"})
    )[1]["hits"]
    folder = http.app.data / "jobs" / data["id"] / "index"
    for suffix in ("txt", "md", "srt"):
        assert "Synthetic speech test" in (folder / f"transcript.{suffix}").read_text("utf-8")
    assert request(http, "/api/transcript?" + urlencode({"id": data["id"]}))[1]["total"] == 1
    from frameproof.web_jobs import Jobs

    restored = Jobs(http.app.data / "jobs")
    assert restored.rows[data["id"]]["state"] == "done"


def test_worker_error_persisted_and_released(server):
    http, media = server
    job = http.app.jobs.start([str(media / "missing.mp4"), "--no-transcribe"], "bad")
    row = wait_job(http, job["id"])
    assert row["state"] == "error"
    assert http.app.jobs.process is None


def test_finished_job_can_be_deleted_without_touching_source(server):
    http, media = server
    source = media / "source.mp4"
    source.write_bytes(b"source")
    job = http.app.jobs.start([str(media / "missing.mp4"), "--no-transcribe"], "remove me")
    assert wait_job(http, job["id"])["state"] == "error"
    folder = http.app.data / "jobs" / job["id"]
    assert folder.is_dir()

    assert request(http, "/api/delete-job", {"id": job["id"]}) == (200, {"ok": True})
    assert not folder.exists()
    assert source.read_bytes() == b"source"
    assert request(http, "/api/jobs")[1] == []
    assert request(http, "/api/job?" + urlencode({"id": job["id"]}))[0] == 400


def test_active_job_cannot_be_deleted(server, monkeypatch):
    import frameproof.web_jobs as jobs_module

    http, _ = server
    original = jobs_module.subprocess.Popen

    def fake_worker(args, **kwargs):
        return original([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

    monkeypatch.setattr(jobs_module.subprocess, "Popen", fake_worker)
    job = http.app.jobs.start([], "active")
    code, data = request(http, "/api/delete-job", {"id": job["id"]})
    assert code == 400
    assert "Сначала остановите" in data["error"]


def test_cancel_kills_process_tree_and_allows_next_job(server, monkeypatch):
    import sys

    import psutil

    import frameproof.web_jobs as jobs_module

    http, media = server
    original = jobs_module.subprocess.Popen

    def fake_worker(args, **kwargs):
        return original(
            [
                sys.executable,
                "-u",
                "-c",
                'import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); print(p.pid,flush=True); time.sleep(60)',
            ],
            **kwargs,
        )

    monkeypatch.setattr(jobs_module.subprocess, "Popen", fake_worker)
    row = http.app.jobs.start([], "cancel test")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        log = http.app.jobs.detail(row["id"]).get("log", "").strip()
        if log:
            break
        time.sleep(0.05)
    child = int(log)
    assert psutil.pid_exists(child)
    with pytest.raises(ValueError, match="Уже"):
        http.app.jobs.start([], "duplicate")
    assert request(http, "/api/shutdown", {})[0] == 400
    assert request(http, "/api/cancel", {})[0] == 200
    assert wait_job(http, row["id"])["state"] == "cancelled"
    assert not psutil.pid_exists(child)
    assert http.app.jobs.process is None
    monkeypatch.setattr(jobs_module.subprocess, "Popen", original)
    new = http.app.jobs.start([str(media / "missing.mp4"), "--no-transcribe"], "next")
    assert wait_job(http, new["id"])["state"] == "error"


def test_url_and_preflight_validation(server, monkeypatch):
    from frameproof import web

    http, _ = server
    monkeypatch.setattr(
        web,
        "readiness",
        lambda: {
            "items": [
                {"id": name, "installed": True}
                for name in ("ffmpeg", "numpy", "yt_dlp", "whisper")
            ]
        },
    )
    args = http.app.arguments(
        {"source": "url", "target": "https://youtube.com/watch?v=abc"}
    )
    assert args[0].endswith("?v=abc")
    assert (
        request(
            http, "/api/preflight", {"source": "upload", "target": "", "speech": "off"}
        )[0]
        == 200
    )
    for target in [
        "file:///etc/passwd",
        "https://user:pass@host/video",
        "https://host/video?token=secret",
    ]:
        with pytest.raises(ValueError):
            http.app.arguments({"source": "url", "target": target})


def test_shutdown_endpoint_when_idle(server):
    http, _ = server
    assert request(http, "/api/shutdown", {}) == (200, {"ok": True})


def test_windows_and_apple_readiness(monkeypatch):
    import frameproof.readiness as ready

    monkeypatch.setattr(ready, "module_exists", lambda name: False)
    monkeypatch.setattr(ready.shutil, "which", lambda name: None)
    monkeypatch.setattr(ready.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ready.platform, "machine", lambda: "arm64")
    data = ready.readiness()
    assert data["recommended_engine"] == "mlx"
    assert {"mlx", "vision"} <= {x["id"] for x in data["items"]}
    assert data["ocr"]["default"] == "vision"
    assert [item["id"] for item in data["ocr"]["options"]] == ["vision"]
    assert "tesseract" not in {item["id"] for item in data["items"]}
    monkeypatch.setattr(ready.platform, "system", lambda: "Windows")
    data = ready.readiness()
    assert any(x["id"] == "windows" and "winsdk" in x["command"] for x in data["items"])
    assert data["ocr"]["default"] == "windows"
    assert [item["id"] for item in data["ocr"]["options"]] == ["windows"]
    assert "tesseract" not in {item["id"] for item in data["items"]}


def test_linux_readiness_exposes_only_tesseract_for_ocr(monkeypatch):
    import frameproof.readiness as ready

    monkeypatch.setattr(ready.platform, "system", lambda: "Linux")
    data = ready.readiness()
    assert data["ocr"] == {
        "default": "tesseract",
        "options": [{"id": "tesseract", "label": "Tesseract"}],
    }


def test_windows_install_command_with_call_operator(monkeypatch):
    import frameproof.readiness as ready

    monkeypatch.setattr(ready.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        ready.sys,
        "executable",
        r"C:\Folder with spaces\frameprof+\.venv\Scripts\python.exe",
    )
    items = {item["id"]: item for item in ready.readiness()["items"]}
    assert items["yt_dlp"]["command"] == (
        '& "C:\\Folder with spaces\\frameprof+\\.venv\\Scripts\\python.exe" -m pip install yt-dlp'
    )
    assert items["whisper"]["command"].startswith('& "')


def test_linux_tesseract_install_command(monkeypatch):
    import frameproof.readiness as ready

    monkeypatch.setattr(ready.platform, "system", lambda: "Linux")
    item = next(x for x in ready.readiness()["items"] if x["id"] == "tesseract")
    assert (
        item["command"]
        == "sudo apt install tesseract-ocr tesseract-ocr-rus"
    )
    assert "rus" in item["purpose"] and "eng" in item["purpose"]
    assert "--list-langs" in item["purpose"]


def test_install_api_confirmation_csrf_and_allowed_fields(server, monkeypatch):
    http, _ = server
    calls = []
    monkeypatch.setattr(
        http.app.installations,
        "start",
        lambda component, request_id: calls.append(component) or {"state": "running"},
    )
    body = {"component": "tesseract", "request_id": "request-1", "confirmed": True}
    assert (
        request(http, "/api/install", body, headers={"X-Frameproof-Token": ""})[0]
        == 403
    )
    assert request(http, "/api/install", {**body, "command": "calc"})[0] == 400
    assert request(http, "/api/install", {**body, "confirmed": False})[0] == 400
    assert not calls
    assert request(http, "/api/install", body)[0] == 202
    assert calls == ["tesseract"]
    assert request(http, "/api/install")[0] == 200


def test_install_blocks_shutdown_and_video(server, monkeypatch):
    http, _ = server
    http.app.installations.active = True
    monkeypatch.setattr(http.app, "arguments", lambda body: ["video.mp4"])
    assert request(http, "/api/shutdown", {})[0] == 400
    assert request(http, "/api/index", {"target": "video.mp4"})[0] == 400
    http.app.installations.active = False
    http.app.jobs.active = "busy"
    assert (
        request(
            http,
            "/api/install",
            {"component": "tesseract", "request_id": "request-1", "confirmed": True},
        )[0]
        == 400
    )
    http.app.jobs.active = None
