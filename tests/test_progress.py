import json

import pytest

from frameproof import progress


def test_progress_file_and_stage_reset(tmp_path, monkeypatch):
    path = tmp_path / "progress.json"
    monkeypatch.setenv("FRAMEPROOF_PROGRESS_FILE", str(path))
    progress.report("Извлечение кадров", 2, 8)
    assert progress.read(path, "running")["percent"] == 25
    progress.report("Распознавание речи")
    assert progress.read(path, "running")["percent"] is None
    assert progress.read(path, "done")["percent"] == 100
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.parametrize("state", ["error", "cancelled", "interrupted", "cancelling"])
def test_terminal_failure_never_reports_completion(tmp_path, state):
    path = tmp_path / "progress.json"
    path.write_text(json.dumps({"stage": "Извлечение", "completed": 8, "total": 8}))
    assert progress.read(path, state)["percent"] is None


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "[]",
        '{"stage":"x","total":0,"completed":0}',
        '{"stage":"x","total":1,"completed":2}',
    ],
)
def test_invalid_progress_is_safe(tmp_path, payload):
    path = tmp_path / "progress.json"
    path.write_text(payload)
    assert progress.read(path, "running")["percent"] is None


def test_missing_output_directory_cannot_break_worker(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "FRAMEPROOF_PROGRESS_FILE", str(tmp_path / "missing" / "progress.json")
    )
    progress.report("stage")


def test_all_windows_dependencies_have_installers(monkeypatch):
    from frameproof import installers, readiness

    monkeypatch.setattr(readiness.platform, "system", lambda: "Windows")
    monkeypatch.setattr(readiness, "module_exists", lambda _: False)
    monkeypatch.setattr(readiness.shutil, "which", lambda _: None)
    monkeypatch.setattr(readiness, "refresh_path", lambda: None)
    items = readiness.readiness()["items"]
    assert {x["id"] for x in items} == set(installers.PIP | installers.WINGET)
    assert all(x["can_install"] and x["command"] for x in items)
