"""Per-bar artifact sink: one folder per candle, plain files inside.

Used by the engine to capture, for every bar processed, the exact inputs
each strategy saw and the exact outputs each strategy produced. Designed
for the seminar demo and post-hoc audit; not on the hot path for production
runs (gated by `run.dump_bar_artifacts`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def bar_folder_name(index: int, *, total: int) -> str:
    """Zero-pad ``index`` to the width of ``total``.

    A 480-bar run yields ``0001`` ... ``0480``. A 10-bar run yields
    ``01`` ... ``10``. A 5-bar run yields ``1`` ... ``5`` (width 1).
    """
    if total < 1:
        raise ValueError(f"total must be >= 1, got {total}")
    if index < 1 or index > total:
        raise ValueError(f"index {index} out of range [1, {total}]")
    width = len(str(total))
    return str(index).zfill(width)


class BarArtifactSink:
    """Owns one bar folder. Writers are explicit (text / json / bytes).

    Folder is created on first write to keep the no-op path (sink built
    but nothing written) cheap.
    """

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._ensured = False

    @property
    def folder(self) -> Path:
        return self._folder

    def _ensure(self) -> None:
        if not self._ensured:
            self._folder.mkdir(parents=True, exist_ok=True)
            self._ensured = True

    def write_text(self, name: str, content: str) -> None:
        self._ensure()
        (self._folder / name).write_text(content, encoding="utf-8")

    def write_json(self, name: str, payload: Any) -> None:
        self._ensure()
        (self._folder / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def write_bytes(self, name: str, payload: bytes) -> None:
        self._ensure()
        (self._folder / name).write_bytes(payload)
