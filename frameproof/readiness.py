"""Cheap diagnostics: never load torch/MLX or allocate GPU memory in the server."""

import importlib.util
import platform
import shutil
import subprocess
import sys

from .installers import PIP, WINGET, refresh_path


def ocr_options(system: str):
    """Return the OCR choices that can run on this operating system.

    The browser must not offer an engine that the host can never execute.  Keep
    the labels beside the host capability instead of guessing the browser OS:
    the browser may be connected through an SSH tunnel.
    """
    choices = {
        "Windows": [{"id": "windows", "label": "Windows OCR"}],
        "Darwin": [{"id": "vision", "label": "Apple Vision OCR"}],
    }.get(system, [{"id": "tesseract", "label": "Tesseract"}])
    return {"default": choices[0]["id"], "options": choices}


def module_exists(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def readiness():
    refresh_path()
    system = platform.system()
    apple = system == "Darwin" and platform.machine().lower() in ("arm64", "aarch64")
    selected_ocr = {option["id"] for option in ocr_options(system)["options"]}
    pip = (
        ("& " if system == "Windows" else "")
        + '"'
        + sys.executable
        + '" -m pip install '
    )
    ffmpeg_command = {
        "Windows": "winget install --id Gyan.FFmpeg --exact",
        "Darwin": "brew install ffmpeg",
    }.get(system, "sudo apt install ffmpeg")
    entries = [
        (
            "psutil",
            "Управление процессами (psutil)",
            module_exists("psutil"),
            "Отмена обработки и освобождение ресурсов",
            pip + "psutil",
            "https://psutil.readthedocs.io/",
        ),
        (
            "ffmpeg",
            "FFmpeg и FFprobe",
            bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
            "Обработка любого видео",
            ffmpeg_command,
            "https://ffmpeg.org/download.html",
        ),
        (
            "numpy",
            "NumPy",
            module_exists("numpy"),
            "Анализ изменений изображения",
            pip + "numpy",
            "https://numpy.org/install/",
        ),
        (
            "yt_dlp",
            "yt-dlp",
            module_exists("yt_dlp"),
            "Загрузка по ссылке",
            pip + "yt-dlp",
            "https://github.com/yt-dlp/yt-dlp#installation",
        ),
        (
            "js",
            "JavaScript-рантайм",
            any(shutil.which(x) for x in ("deno", "node", "bun", "quickjs")),
            "Загрузка с YouTube",
            "winget install --id OpenJS.NodeJS.LTS --exact"
            if system == "Windows"
            else "",
            "https://nodejs.org/en/download",
        ),
        (
            "whisper",
            "Whisper",
            module_exists("whisper"),
            "Локальная речь на CPU / совместимом GPU",
            pip + "openai-whisper",
            "https://github.com/openai/whisper",
        ),
    ]
    if "tesseract" in selected_ocr:
        entries.append(
            (
                "tesseract",
                "Tesseract OCR",
                bool(shutil.which("tesseract")),
                "Текст на экране; нужны языки rus и eng. "
                "После установки проверьте tesseract --list-langs.",
                "sudo apt install tesseract-ocr tesseract-ocr-rus"
                if system == "Linux"
                else "",
                "https://tesseract-ocr.github.io/tessdoc/Installation.html",
            )
        )
    if apple:
        entries.append(
            (
                "mlx",
                "MLX Whisper",
                module_exists("mlx_whisper"),
                "Речь на Apple Silicon / Metal",
                pip + "mlx-whisper",
                "https://github.com/ml-explore/mlx-examples/tree/main/whisper",
            )
        )
    if "vision" in selected_ocr:
        entries.append(
            (
                "vision",
                "Apple Vision OCR",
                bool(shutil.which("swiftc")),
                "Текст на экране",
                "xcode-select --install",
                "https://developer.apple.com/xcode/resources/",
            )
        )
    if "windows" in selected_ocr:
        entries.append(
            (
                "windows",
                "Windows OCR",
                module_exists("winsdk"),
                "Текст на экране; языки проверяются при обработке",
                pip + "winsdk",
                "https://pypi.org/project/winsdk/",
            )
        )
    items = [
        {
            "id": i,
            "name": n,
            "installed": ok,
            "purpose": p,
            "command": c,
            "url": u,
            "can_install": system == "Windows" and i in PIP | WINGET,
            "ready": ok,
        }
        for i, n, ok, p, c, u in entries
    ]
    tess = next((x for x in items if x["id"] == "tesseract"), None)
    if tess and tess["installed"]:
        try:
            import os

            args = [shutil.which("tesseract"), "--list-langs"]
            if os.environ.get("FRAMEPROOF_TESSDATA"):
                args += ["--tessdata-dir", os.environ["FRAMEPROOF_TESSDATA"]]
            result = subprocess.run(
                args,
                capture_output=True,
                timeout=5,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if system == "Windows" else 0,
            )
            languages = set(result.stdout.decode("utf-8", "replace").splitlines())
            missing = sorted({"rus", "eng"} - languages)
            tess["ready"] = result.returncode == 0 and not missing
            tess["detail"] = (
                "Языки готовы: rus, eng"
                if tess["ready"]
                else "Не готовы языки: " + ", ".join(missing)
            )
        except (OSError, subprocess.TimeoutExpired):
            tess["ready"] = False
            tess["detail"] = "Не удалось проверить языки Tesseract."
    return {
        "system": system,
        "machine": platform.machine(),
        "python": platform.python_version(),
        "environment": sys.prefix,
        "isolated": sys.prefix != sys.base_prefix,
        "recommended_engine": "mlx" if apple else "whisper",
        "gpu": "NVIDIA utility обнаружена; совместимость движка ещё не проверена"
        if shutil.which("nvidia-smi")
        else "GPU не проверена. Автовыбор устройства выполняется движком при обработке.",
        "ocr": ocr_options(system),
        "items": items,
    }
