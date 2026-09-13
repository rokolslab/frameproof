"""Browser fixture: a real harmless worker emits progress; no video/models loaded."""

import subprocess
import sys
from types import SimpleNamespace

from frameproof import web, web_jobs


def main():
    real_popen = subprocess.Popen
    code = (
        "import time; from frameproof.progress import report; "
        "report('ТЕСТ: извлечение кадров', 1, 4); time.sleep(90); "
        "report('ТЕСТ: распознавание речи'); time.sleep(25); raise SystemExit(1)"
    )
    web_jobs.subprocess = SimpleNamespace(
        Popen=lambda args, **kwargs: real_popen([sys.executable, "-c", code], **kwargs),
        CREATE_NO_WINDOW=subprocess.CREATE_NO_WINDOW,
        STDOUT=subprocess.STDOUT,
        DEVNULL=subprocess.DEVNULL,
    )
    server = web.create_server(".web-data/progress-ui-test", (), port=8768)
    server.app.jobs.start([], "ТЕСТ: прогресс рабочего процесса")
    try:
        server.serve_forever()
    finally:
        server.app.jobs.cancel()
        server.server_close()


if __name__ == "__main__":
    main()
