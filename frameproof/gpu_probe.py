"""Small, JSON-only CUDA probe run outside the web server process."""

from __future__ import annotations

import json
import shutil


def probe() -> dict:
    result = {
        "nvidia_detected": bool(shutil.which("nvidia-smi")),
        "cuda_available": False,
        "torch_version": None,
        "torch_cuda": None,
        "device_name": None,
        "memory_total_mb": None,
        "detail": "PyTorch не установлен.",
    }
    try:
        import torch
    except Exception as exc:  # The UI needs the import failure, never a traceback.
        result["detail"] = f"PyTorch недоступен: {exc}"
        return result

    result["torch_version"] = torch.__version__
    result["torch_cuda"] = torch.version.cuda
    try:
        available = torch.cuda.is_available()
    except Exception as exc:
        result["detail"] = f"CUDA не инициализируется: {exc}"
        return result
    result["cuda_available"] = available
    if not available:
        result["detail"] = "PyTorch установлен без доступной CUDA."
        return result
    try:
        properties = torch.cuda.get_device_properties(0)
        result["device_name"] = torch.cuda.get_device_name(0)
        result["memory_total_mb"] = round(properties.total_memory / 1024**2)
        result["detail"] = "CUDA готова для Whisper."
    except Exception as exc:
        result["cuda_available"] = False
        result["detail"] = f"CUDA не дала сведения об устройстве: {exc}"
    return result


def main() -> None:
    print(json.dumps(probe(), ensure_ascii=False))


if __name__ == "__main__":
    main()
