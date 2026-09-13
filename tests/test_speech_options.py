import json
import sys

import pytest

from frameproof import transcribe as speech


def test_whisper_uses_venv_python_and_selected_device(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    (tmp_path / "audio.json").write_text(
        json.dumps(
            {"segments": [{"start": 0, "end": 1, "text": "hello"}], "language": "en"}
        )
    )
    monkeypatch.setattr(speech.importlib.util, "find_spec", lambda name: object())
    commands = []
    monkeypatch.setattr("frameproof.util.run", lambda cmd: commands.append(cmd))
    result = speech._openai_whisper(str(audio), "en", "base", "cpu")
    assert commands[0][:3] == [sys.executable, "-m", "whisper"]
    assert commands[0][commands[0].index("--model") + 1] == "base"
    assert commands[0][commands[0].index("--device") + 1] == "cpu"
    assert result.segments[0].text == "hello"


def test_explicit_mlx_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(speech, "_mlx_whisper", lambda *a: None)

    def forbidden(*args):
        pytest.fail("Explicit MLX must not use Whisper")

    monkeypatch.setattr(speech, "_openai_whisper", forbidden)
    with pytest.raises(RuntimeError):
        speech.transcribe_audio("audio", engine="mlx")


def test_auto_falls_back_and_passes_options(monkeypatch):
    monkeypatch.setattr(speech, "_mlx_whisper", lambda *a: None)
    calls = []

    def fallback(*args):
        calls.append(args)
        return speech.Transcript(
            segments=[speech.Segment(i=0, t0=0, t1=1, text="test")],
            source="test",
            language="en",
        )

    monkeypatch.setattr(speech, "_openai_whisper", fallback)
    speech.transcribe_audio("audio", model="tiny", device="cpu")
    assert calls == [("audio", None, "tiny", "cpu")]


@pytest.mark.parametrize(
    "options", [{"engine": "bad"}, {"model": "../secret"}, {"device": "shell"}]
)
def test_reject_unknown_speech_options(options):
    with pytest.raises(ValueError):
        speech.transcribe_audio("audio", **options)
