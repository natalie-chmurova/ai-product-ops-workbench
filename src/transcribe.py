"""Audio → text, so the pipeline can start from a recording, not just a transcript.

Uses mlx-whisper (Apple-silicon optimized) to transcribe locally — no audio ever
leaves the machine, and no per-minute API cost. The model is downloaded once on
first use and cached.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .client import WorkbenchError

# A small, fast model — plenty for meeting speech; swap for a larger repo if needed.
MODEL = "mlx-community/whisper-base-mlx"

AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".aiff", ".aac", ".mp4", ".mov", ".ogg", ".flac"}


def is_audio(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_SUFFIXES


def transcribe_audio(path: str | Path) -> str:
    """Transcribe an audio/video file to plain text.

    Audio is optional: the text pipeline needs neither mlx-whisper nor ffmpeg, so they
    are not base dependencies, and a machine without them is told which one is missing.
    """
    # mlx-whisper decodes audio by running the ffmpeg command. Checked first, because
    # without it the transcription ends in a FileNotFoundError about a program the
    # person never asked for.
    if shutil.which("ffmpeg") is None:
        raise WorkbenchError(
            "Transcribing audio needs ffmpeg, which is not installed.\n"
            "  macOS: brew install ffmpeg\n"
            "  Or paste a text transcript instead."
        )
    try:
        import mlx_whisper  # imported lazily so text-only runs don't need it
    except ImportError as exc:
        raise WorkbenchError(
            "Transcribing audio needs the optional audio extras (Apple Silicon Macs):\n"
            "  pip install -r requirements-audio.txt\n"
            "  Or paste a text transcript instead."
        ) from exc

    path = str(path)
    result = mlx_whisper.transcribe(path, path_or_hf_repo=MODEL)
    return (result.get("text") or "").strip()
