"""Audio is optional: a machine without it gets a sentence, not a traceback.

The text pipeline needs neither mlx-whisper nor ffmpeg, so neither is a base
dependency. A person who then hands the CLI or the app an audio file has to be told
which of the two is missing and how to get it.
"""

from __future__ import annotations

import sys

import pytest

from src import transcribe
from src.client import WorkbenchError


def test_audio_without_the_audio_extras_says_how_to_install_them(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)  # import now raises ImportError
    monkeypatch.setattr(transcribe.shutil, "which", lambda name: "/usr/bin/" + name)
    with pytest.raises(WorkbenchError) as exc:
        transcribe.transcribe_audio("meeting.m4a")
    assert "requirements-audio.txt" in str(exc.value)


def test_audio_without_ffmpeg_says_how_to_install_it(monkeypatch):
    # mlx-whisper decodes audio by running the ffmpeg command; without it the call ends
    # in a FileNotFoundError naming a program the person never asked for.
    monkeypatch.setattr(transcribe.shutil, "which", lambda name: None)
    with pytest.raises(WorkbenchError) as exc:
        transcribe.transcribe_audio("meeting.m4a")
    assert "ffmpeg" in str(exc.value)
