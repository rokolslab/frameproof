"""Manual browser fixture. Runs harmless PowerShell, never installs packages.

Run from the repository via runpy.run_path('tests/serve_install_ui.py', run_name='__main__').
"""

import sys

from frameproof import installers, readiness, web


def main():
    server = web.create_server(".web-data/install-ui-test", (), port=8768)
    original = readiness.readiness

    def fixture_readiness():
        report = original()
        installed = server.app.installations.row.get("state") == "done"
        report["items"] = [
            {
                "id": "numpy",
                "name": "ТЕСТ: установка без изменений системы",
                "installed": installed,
                "ready": installed,
                "can_install": True,
                "purpose": "Тестовый PowerShell: ожидание и вывод, без pip, winget и записи PATH.",
                "command": "Write-Output test",
                "url": "https://numpy.org/",
            }
        ]
        return report

    web.readiness = fixture_readiness
    # Verifier returns actual NumPy presence; UI starts missing to exercise the flow.
    installers.script_for = lambda _: (
        "Start-Sleep -Seconds 3; Write-Output test; exit "
        + ("1" if "--fail" in sys.argv else "0")
    )
    print("Test-only UI: http://127.0.0.1:8768", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
