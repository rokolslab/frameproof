from pathlib import Path

from frameproof.__main__ import build_parser
from frameproof.web import _inside_index


def test_web_command_defaults_to_loopback():
    args = build_parser().parse_args(["web", "--no-browser"])
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.no_browser is True


def test_frame_path_must_stay_under_index(tmp_path: Path):
    out = tmp_path / "index"
    out.mkdir()
    assert _inside_index(str(out / "frames" / "f0001.jpg"), str(out))
    assert not _inside_index(str(tmp_path / "outside.jpg"), str(out))


def test_web_document_preserves_explicit_frame_gate():
    page = (Path(__file__).parents[1] / "frameproof" / "assets" / "web" / "index.html").read_text(encoding="utf-8")
    assert "Открыть кадр" in page
    assert "type=\"search\"" in page
    script = (Path(__file__).parents[1] / "frameproof" / "assets" / "web" / "app.js").read_text(encoding="utf-8")
    assert "compositionstart" in script
    assert "configureOcr" in script
