"""No real installs: validate PowerShell scripts and the actual process lifecycle."""

import base64
import subprocess
import sys
import time

import pytest

from frameproof import installers


@pytest.mark.parametrize("component", list(installers.PIP | installers.WINGET))
def test_powershell_syntax(component):
    if sys.platform != "win32":
        pytest.skip("PowerShell syntax check on Windows")
    script = installers.script_for(component)
    encoded = base64.b64encode(script.encode("utf-8")).decode()
    validator = (
        "$tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseInput([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
        + encoded
        + "')),[ref]$tokens,[ref]$errors) | Out-Null; if ($errors.Count) { $errors | Out-String | Write-Output; exit 1 }"
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(validator.encode("utf-16-le")).decode(),
        ],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    if component in installers.WINGET:
        assert "--silent" in script and "--no-upgrade" in script
        assert "--interactive" not in script
    assert "'User'" in script and "setx" not in script


def test_no_arbitrary_command():
    with pytest.raises(ValueError):
        installers.script_for("yt_dlp; Start-Process calc")
    assert installers.ps_quote("a'b") == "'a''b'"


def test_system_python_rejected(monkeypatch):
    monkeypatch.setattr(installers.sys, "prefix", sys.base_prefix)
    with pytest.raises(ValueError, match="venv"):
        installers.script_for("numpy")


@pytest.mark.parametrize(
    "exit_code,ready,expected",
    [(0, True, "done"), (1, True, "error"), (0, False, "error")],
)
def test_real_process_state_and_dedup(
    tmp_path, monkeypatch, exit_code, ready, expected
):
    from frameproof import readiness

    if sys.platform != "win32":
        pytest.skip("Windows process lifecycle")
    monkeypatch.setattr(
        installers,
        "script_for",
        lambda _: f"Start-Sleep -Milliseconds 500; Write-Output test; exit {exit_code}",
    )
    monkeypatch.setattr(installers, "refresh_path", lambda: None)
    monkeypatch.setattr(
        readiness, "readiness", lambda: {"items": [{"id": "numpy", "installed": ready}]}
    )
    manager = installers.Installations(tmp_path)
    row = manager.start("numpy", "request-1")
    assert manager.start("numpy", "request-1") == row
    with pytest.raises(ValueError, match="завершения"):
        manager.start("numpy", "request-2")
    deadline = time.monotonic() + 10
    while manager.active and time.monotonic() < deadline:
        time.sleep(0.05)
    assert manager.status()["state"] == expected
    assert "test" in manager.status()["log"]
    assert (tmp_path / "last.json").exists()


def test_tesseract_user_data_and_no_global_python_path():
    script = installers.script_for("tesseract")
    assert "@('rus','eng')" in script
    assert "tessdata_fast/4.1.0/" in script
    assert "'Path',$userPath,'User'" in script
    assert "-1978335135" in script  # WinGet PACKAGE_ALREADY_INSTALLED
    assert "RunAs" not in script  # WinGet/installer owns elevation, not the server.
    assert "-Force" not in script.split("Move-Item")[1].split("\n")[0]


def test_refresh_path_preserves_existing_entries(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows registry paths")
    monkeypatch.setenv("PATH", r"C:\keep-this-entry")
    monkeypatch.delenv("FRAMEPROOF_TESSDATA", raising=False)
    installers.refresh_path()
    paths = installers.os.environ["PATH"].split(";")
    assert paths[0] == r"C:\keep-this-entry"
    assert any(p.endswith("Tesseract-OCR") for p in paths)
    previous = installers.os.environ["PATH"]
    installers.refresh_path()
    assert installers.os.environ["PATH"] == previous


@pytest.mark.parametrize(
    "languages,ready", [(b"eng\nosd\n", False), (b"eng\nrus\n", True)]
)
def test_readiness_checks_languages(monkeypatch, languages, ready):
    from types import SimpleNamespace

    from frameproof import readiness

    monkeypatch.setattr(readiness, "refresh_path", lambda: None)
    monkeypatch.setattr(
        readiness.shutil,
        "which",
        lambda name: "tesseract.exe" if name == "tesseract" else None,
    )
    monkeypatch.setattr(
        readiness.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=languages),
    )
    item = next(x for x in readiness.readiness()["items"] if x["id"] == "tesseract")
    assert item["installed"]
    assert item["ready"] is ready
