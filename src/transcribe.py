"""Audio → text, so the pipeline can start from a recording, not just a transcript.

Uses mlx-whisper (Apple-silicon optimized) to transcribe locally — no audio ever
leaves the machine, and no per-minute API cost. The model is downloaded once on
first use and cached.
"""

from __future__ import annotations

from pathlib import Path

# A small, fast model — plenty for meeting speech; swap for a larger repo if needed.
MODEL = "mlx-community/whisper-base-mlx"

AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".aiff", ".aac", ".mp4", ".mov", ".ogg", ".flac"}


def is_audio(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_SUFFIXES


def transcribe_audio(path: str | Path) -> str:
    """Transcribe an audio/video file to plain text."""
    import mlx_whisper  # imported lazily so text-only runs don't need it

    path = str(path)
    result = mlx_whisper.transcribe(path, path_or_hf_repo=MODEL)
    return (result.get("text") or "").strip()
