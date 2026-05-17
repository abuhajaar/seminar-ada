from pathlib import Path

from data.paths import aggtrades_parquet_path, cvd_csv_path, ohlcv_csv_path


def test_ohlcv_path_normalizes_symbol(tmp_path: Path):
    p = ohlcv_csv_path("BTC/USDT", "1h", root=tmp_path)
    assert p == tmp_path / "ohlcv" / "BTCUSDT_1h.csv"


def test_aggtrades_path(tmp_path: Path):
    p = aggtrades_parquet_path("BTC/USDT", root=tmp_path)
    assert p == tmp_path / "aggtrades" / "BTCUSDT.parquet"


def test_cvd_csv_path(tmp_path: Path):
    p = cvd_csv_path("ETH/USDT", "4h", root=tmp_path)
    assert p == tmp_path / "cvd" / "ETHUSDT_4h.csv"
