"""Windows-only, allowlisted dependency installation. Never execute browser commands."""

import importlib
import json
import os
import platform
import subprocess
import sys
import threading
from pathlib import Path

PIP = {
    "psutil": "psutil",
    "numpy": "numpy",
    "yt_dlp": "yt-dlp",
    "whisper": "openai-whisper",
    "windows": "winsdk",
}
# NVIDIA Blackwell (including RTX 5060 Ti) starts with CUDA 12.8 support.
TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
WINGET = {
    "ffmpeg": "Gyan.FFmpeg",
    "js": "OpenJS.NodeJS.LTS",
    "tesseract": "UB-Mannheim.TesseractOCR",
}


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def tessdata_dir():
    return (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        / "Frameproof"
        / "tessdata"
    )


def refresh_path():
    """Keep existing PATH; append registry updates and known installed binaries."""
    if platform.system() != "Windows":
        return
    import winreg

    entries = os.environ.get("PATH", "").split(os.pathsep)
    for hive, key in [
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    ]:
        try:
            with winreg.OpenKey(hive, key) as handle:
                entries.extend(
                    os.path.expandvars(winreg.QueryValueEx(handle, "Path")[0]).split(
                        os.pathsep
                    )
                )
        except OSError:
            pass
    entries.extend(
        [
            str(Path(sys.executable).parent),
            str(
                Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "Tesseract-OCR"
            ),
            str(
                Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                / "Programs"
                / "Tesseract-OCR"
            ),
        ]
    )
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys(x for x in entries if x))
    data = tessdata_dir()
    if all((data / f"{lang}.traineddata").is_file() for lang in ("rus", "eng")):
        os.environ["FRAMEPROOF_TESSDATA"] = str(data)


def script_for(component):
    if component not in PIP | WINGET:
        raise ValueError("Установка этого компонента не поддерживается.")
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new()",
        "try {",
    ]
    if component in PIP:
        if sys.prefix == sys.base_prefix:
            raise ValueError(
                "Автоустановка Python-пакетов разрешена только в .venv приложения."
            )
        if component == "whisper":
            lines += [
                "$nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue",
                "if ($nvidia) {",
                f"  & {ps_quote(sys.executable)} -m pip --disable-pip-version-check --no-input install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url {TORCH_CUDA_INDEX}",
                '  if ($LASTEXITCODE -ne 0) { throw "Не удалось установить CUDA-вариант PyTorch: $LASTEXITCODE" }',
                "}",
            ]
        lines += [
            f"& {ps_quote(sys.executable)} -m pip --disable-pip-version-check --no-input install {PIP[component]}",
            'if ($LASTEXITCODE -ne 0) { throw "pip завершился с кодом $LASTEXITCODE" }',
        ]
        if component == "whisper":
            lines += [
                "if ($nvidia) {",
                f"  $gpu = (& {ps_quote(sys.executable)} -m frameproof.gpu_probe | ConvertFrom-Json)",
                '  if (-not $gpu.cuda_available) { throw "NVIDIA обнаружена, но CUDA PyTorch не готов: $($gpu.detail)" }',
                "}",
            ]
    else:
        # WinGet invokes the selected installer's UAC itself. Never elevate the server.
        lines += [
            "$winget = Get-Command winget -ErrorAction Stop",
            f"& $winget.Source install --id {WINGET[component]} --exact --source winget --no-upgrade --silent --disable-interactivity --accept-package-agreements --accept-source-agreements",
            # UPDATE_NOT_APPLICABLE / PACKAGE_ALREADY_INSTALLED: still repair PATH/languages.
            'if ($LASTEXITCODE -notin @(0,-1978335189,-1978335135)) { throw "winget завершился с кодом $LASTEXITCODE. Проверьте UAC и журнал." }',
        ]
    if component == "tesseract":
        lines += [
            f"$dataDir = {ps_quote(tessdata_dir())}",
            "New-Item -ItemType Directory -Path $dataDir -Force | Out-Null",
            "foreach ($language in @('rus','eng')) {",
            "  $destination = Join-Path $dataDir ($language + '.traineddata')",
            "  if (-not (Test-Path -LiteralPath $destination)) {",
            "    $download = $destination + '.download'",
            "    Invoke-WebRequest -UseBasicParsing -TimeoutSec 180 -Uri ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/' + $language + '.traineddata') -OutFile $download",
            "    Move-Item -LiteralPath $download -Destination $destination",
            "  }",
            "}",
        ]
    # Preserve, never replace, existing user and machine PATH. No setx truncation.
    lines += [
        "$machinePath = [Environment]::GetEnvironmentVariable('Path','Machine')",
        "$userPath = [string][Environment]::GetEnvironmentVariable('Path','User')",
        "$env:Path = $machinePath + ';' + $userPath + ';' + $env:Path",
        r"$candidates = @((Join-Path $env:ProgramFiles 'Tesseract-OCR'), (Join-Path $env:LOCALAPPDATA 'Programs\Tesseract-OCR'))"
        if component == "tesseract"
        else "$candidates = @()",
        "foreach ($candidate in $candidates) {",
        "  if ((Test-Path -LiteralPath $candidate -PathType Container) -and ($userPath -split ';') -notcontains $candidate) { $userPath = $userPath.TrimEnd(';') + ';' + $candidate }",
        "}",
        "[Environment]::SetEnvironmentVariable('Path',$userPath,'User')",
        "Write-Output 'Установка завершена. Проверяем компонент.'",
        "exit 0",
        "} catch { Write-Output $_.Exception.Message; exit 1 }",
    ]
    return "\n".join(lines)


class Installations:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.active = False
        self.row = {"state": "idle", "message": ""}
        self.requests = {}

    def status(self):
        with self.lock:
            row = dict(self.row)
            log = self.root / "install.log"
            if log.exists():
                with log.open("rb") as fh:
                    fh.seek(max(0, log.stat().st_size - 16000))
                    row["log"] = fh.read().decode("utf-8", "replace")
            return row

    def start(self, component, request_id):
        if platform.system() != "Windows":
            raise ValueError("Кнопка установки пока доступна только на Windows.")
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 80:
            raise ValueError("Неверный идентификатор запроса.")
        script = script_for(component)
        with self.lock:
            if request_id in self.requests:
                if self.requests[request_id]["component"] != component:
                    raise ValueError("Этот запрос уже относится к другому компоненту.")
                return dict(self.requests[request_id])
            if self.active:
                raise ValueError("Дождитесь завершения текущей установки.")
            executable = str(
                Path(os.environ.get("SystemRoot", r"C:\Windows"))
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            )
            log = (self.root / "install.log").open("wb")
            try:
                proc = subprocess.Popen(
                    [
                        executable,
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        script,
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                log.close()
                raise
            self.active = True
            self.row = {
                "state": "running",
                "component": component,
                "request_id": request_id,
                "message": "Установка выполняется. Если появился UAC на хосте, подтвердите его. Не завершайте приложение.",
            }
            self.requests[request_id] = self.row
            threading.Thread(
                target=self._wait, args=(proc, log, component), daemon=True
            ).start()
            return dict(self.row)

    def _wait(self, proc, log, component):
        try:
            code = proc.wait()
            log.close()
            refresh_path()
            importlib.invalidate_caches()
            from .readiness import readiness

            item = next(x for x in readiness()["items"] if x["id"] == component)
            ready = item.get("ready", item["installed"])
            success = code == 0 and ready
            if success:
                message = "Компонент установлен и проверен."
            elif component == "whisper":
                message = "Whisper не готов: " + item.get(
                    "detail",
                    "не удалось проверить CUDA PyTorch. Откройте журнал установки.",
                )
            else:
                message = "Установка не подтверждена. Проверьте журнал, PATH и разрешение UAC; затем повторите проверку."
        except Exception as exc:  # noqa: BLE001 - worker must publish its failure state
            success, message, code = False, str(exc), None
        finally:
            log.close()
        with self.lock:
            self.row.update(
                state="done" if success else "error", message=message, exit_code=code
            )
            self.active = False
            (self.root / "last.json").write_text(
                json.dumps(self.row, ensure_ascii=False), encoding="utf-8"
            )
