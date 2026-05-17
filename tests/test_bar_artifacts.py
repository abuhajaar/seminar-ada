from pathlib import Path
import json

import pytest

from core.bar_artifacts import BarArtifactSink, bar_folder_name


def test_bar_folder_name_pads_to_total_width():
    assert bar_folder_name(1, total=480) == "001"
    assert bar_folder_name(480, total=480) == "480"
    assert bar_folder_name(1, total=9) == "1"
    assert bar_folder_name(1, total=10) == "01"


def test_bar_folder_name_rejects_out_of_range():
    with pytest.raises(ValueError):
        bar_folder_name(0, total=480)
    with pytest.raises(ValueError):
        bar_folder_name(481, total=480)


def test_sink_creates_folder_and_writes_text(tmp_path: Path):
    sink = BarArtifactSink(tmp_path / "bars" / "0001")
    sink.write_text("technical_input.txt", "hello prompt")
    out = tmp_path / "bars" / "0001" / "technical_input.txt"
    assert out.read_text(encoding="utf-8") == "hello prompt"


def test_sink_writes_json(tmp_path: Path):
    sink = BarArtifactSink(tmp_path / "bars" / "0001")
    sink.write_json("output.json", {"action": "BUY", "confidence": 0.7})
    payload = json.loads((tmp_path / "bars" / "0001" / "output.json").read_text(encoding="utf-8"))
    assert payload == {"action": "BUY", "confidence": 0.7}


def test_sink_writes_png_bytes(tmp_path: Path):
    sink = BarArtifactSink(tmp_path / "bars" / "0001")
    payload = b"\x89PNG\r\n\x1a\n"
    sink.write_bytes("chart.png", payload)
    out = tmp_path / "bars" / "0001" / "chart.png"
    assert out.read_bytes() == payload
