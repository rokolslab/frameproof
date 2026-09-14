import json
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest
from test_web_api import request
from test_web_api import server as server_fixture

from frameproof import transcript_export as export
from frameproof.transcribe import Segment, Transcript, from_subtitles
from frameproof.web import Application

server = server_fixture


@pytest.fixture
def transcript():
    return Transcript(
        [
            Segment(0, 0, 2.125, "Обсудим план совещания."),
            Segment(
                1,
                3661.9996,
                3665,
                "Решение: подготовить отчёт. <script>alert(1)</script>",
            ),
        ],
        "test",
        "ru",
    )


def managed(http, transcript, state="done"):
    key = "a" * 32
    folder = http.app.data / "jobs" / key / "index"
    export.save(folder, transcript)
    http.app.jobs.rows[key] = {
        "id": key,
        "title": "Совещание",
        "state": state,
        "created": 1,
    }
    http.app.jobs.save(http.app.jobs.rows[key])
    return key, folder


def test_automatic_files_and_subtitle_roundtrip(tmp_path, transcript):
    export.save(tmp_path, transcript)
    assert (
        (tmp_path / "transcript.txt")
        .read_text("utf-8")
        .startswith("Обсудим план совещания.")
    )
    assert "\\<script\\>" in (tmp_path / "transcript.md").read_text("utf-8")
    assert "01:01:02,000" in (tmp_path / "transcript.srt").read_text("utf-8")
    restored = from_subtitles(str(tmp_path / "transcript.srt"))
    assert restored.segments[0].text == transcript.segments[0].text
    assert len(export.read_rows(tmp_path)) == 2
    assert not list(tmp_path.glob("tmp*"))


def test_atomic_failure_preserves_existing_text(tmp_path, monkeypatch):
    path = tmp_path / "transcript.txt"
    path.write_text("Original", encoding="utf-8")

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(export.os, "replace", fail)
    with pytest.raises(OSError):
        export._atomic_write(path, "Changed")
    assert path.read_text("utf-8") == "Original"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "line",
    [
        "{}",
        "null",
        '{"t0": -1,"t1":2,"text":"bad"}',
        '{"t0":0,"t1":NaN,"text":"bad"}',
        '{"t0":2,"t1":1,"text":"bad"}',
        '{"t0":0,"t1":1,"text":23}',
    ],
)
def test_corrupt_transcript_rejected(tmp_path, line):
    (tmp_path / "segments.jsonl").write_text(line, encoding="utf-8")
    with pytest.raises(ValueError, match="повреждён"):
        export.read_rows(tmp_path)


def test_missing_and_empty_transcript(tmp_path):
    assert export.read_rows(tmp_path) == []
    (tmp_path / "index.json").write_text(
        '{"transcript":{"segment_count":1}}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="отсутствует"):
        export.read_rows(tmp_path)


def test_symlink_cannot_read_outside(tmp_path):
    folder = tmp_path / "index"
    folder.mkdir()
    outside = tmp_path / "private.jsonl"
    outside.write_text('{"t0":0,"t1":1,"text":"private"}', encoding="utf-8")
    try:
        (folder / "segments.jsonl").symlink_to(outside)
    except OSError:
        pytest.skip("Symlink permission unavailable")
    with pytest.raises(ValueError, match="путь"):
        export.read_rows(folder)


def test_http_pagination_and_restart(server, transcript):
    http, media = server
    transcript.segments = [Segment(i, i, i + 1, f"Реплика {i}") for i in range(205)]
    key, folder = managed(http, transcript)
    code, page = request(
        http, "/api/transcript?" + urlencode({"id": key, "offset": 100, "limit": 999})
    )
    assert code == 200 and len(page["rows"]) == 100
    assert page["rows"][0]["text"] == "Реплика 100"
    assert page["total"] == 205 and page["saved"]
    assert page["folder"] == str(folder)
    restored = Application(http.app.data, [media])
    assert restored.jobs.rows[key]["state"] == "done"
    assert len(export.read_rows(restored.transcript_path(key))) == 205


@pytest.mark.parametrize("format", ["txt", "md", "srt"])
def test_download_all_text_headers_and_no_frame_access(server, transcript, format):
    http, _ = server
    key, folder = managed(http, transcript)
    url = f"http://127.0.0.1:{http.server_port}/api/transcript?" + urlencode(
        {"id": key, "format": format}
    )
    with urlopen(url) as response:
        assert (
            response.headers["Content-Disposition"]
            == f'attachment; filename="transcript.{format}"'
        )
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        text = response.read().decode("utf-8")
    assert "Обсудим план" in text and "Решение" in text
    assert not (folder / "served.jsonl").exists()


@pytest.mark.parametrize("state", ["error", "cancelled", "interrupted"])
def test_speech_available_when_later_video_stage_fails(server, transcript, state):
    http, _ = server
    key, _ = managed(http, transcript, state)
    assert request(http, f"/api/report?id={key}")[0] == 400
    assert request(http, f"/api/transcript?id={key}")[1]["total"] == 2


def test_legacy_index_without_exports(server, transcript):
    http, media = server
    folder = media / "legacy"
    folder.mkdir()
    (folder / "segments.jsonl").write_text(
        "\n".join(json.dumps(s.as_row()) for s in transcript.segments), encoding="utf-8"
    )
    http.app.registry["legacy"] = str(folder)
    assert request(http, "/api/transcript?id=legacy")[1]["total"] == 2
    assert request(http, "/api/transcript?id=legacy&format=txt")[0] == 200
    assert not (
        folder / "transcript.txt"
    ).exists()  # GET never changes imported indexes.


def test_invalid_requests_and_empty_download(server, transcript):
    http, _ = server
    key, folder = managed(http, transcript)
    for query in [
        "id=unknown",
        "id=../../private",
        f"id={key}&format=../../private",
        f"id={key}&offset=no",
    ]:
        assert request(http, "/api/transcript?" + query)[0] == 400
    assert (
        request(
            http, f"/api/transcript?id={key}", headers={"Origin": "http://evil.test"}
        )[0]
        == 403
    )
    export.save(folder, Transcript([], "test", None))
    assert request(http, f"/api/transcript?id={key}")[1]["total"] == 0
    assert request(http, f"/api/transcript?id={key}&format=txt")[0] == 400


def test_cli_saves_speech_before_frame_analysis(tmp_path, transcript, monkeypatch):
    from types import SimpleNamespace

    from frameproof import __main__ as cli

    monkeypatch.setattr(
        "frameproof.probe.probe",
        lambda *a: SimpleNamespace(
            width=320, height=180, fps=25, duration=5, vfr=False
        ),
    )
    monkeypatch.setattr(cli, "_local_transcript", lambda *a, **kw: transcript)

    def fail(*a, **kw):
        raise RuntimeError("frame analysis failed")

    monkeypatch.setattr("frameproof.analyze.analyze", fail)
    (tmp_path / "meeting.mp4").touch()
    args = cli.build_parser().parse_args(
        ["index", str(tmp_path / "meeting.mp4"), "--out", str(tmp_path / "result")]
    )
    with pytest.raises(RuntimeError, match="frame analysis"):
        args.func(args)
    assert (
        (tmp_path / "result" / "transcript.txt")
        .read_text("utf-8")
        .startswith("Обсудим")
    )
