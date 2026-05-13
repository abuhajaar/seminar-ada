"""Downloader tests use a mocked ccxt exchange and respx-mocked Binance REST."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pandas as pd
import respx

from data.downloader import download_aggtrades, download_ohlcv
from data.paths import aggtrades_parquet_path, ohlcv_csv_path


def _ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=UTC).timestamp() * 1000)


def test_download_ohlcv_writes_csv_and_is_idempotent(tmp_path: Path):
    fake_exchange = MagicMock()
    # ccxt returns: [[ts_ms, open, high, low, close, volume], ...]
    rows = [
        [_ms(datetime(2025, 4, 1, h)), 100 + h, 101 + h, 99 + h, 100.5 + h, 10.0 + h]
        for h in range(24)
    ]
    fake_exchange.parse_timeframe.return_value = 3600  # seconds in 1h
    fake_exchange.fetch_ohlcv.return_value = rows

    out = download_ohlcv(
        symbol="BTC/USDT",
        timeframe="1h",
        start=date(2025, 4, 1),
        end=date(2025, 4, 2),
        exchange=fake_exchange,
        root=tmp_path,
    )
    assert out == ohlcv_csv_path("BTC/USDT", "1h", root=tmp_path)
    assert out.exists()
    df = pd.read_csv(out, parse_dates=["timestamp"])
    assert len(df) == 24
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]

    # Re-running with same args should NOT re-fetch (idempotent).
    fake_exchange.fetch_ohlcv.reset_mock()
    download_ohlcv(
        symbol="BTC/USDT", timeframe="1h",
        start=date(2025, 4, 1), end=date(2025, 4, 2),
        exchange=fake_exchange, root=tmp_path,
    )
    fake_exchange.fetch_ohlcv.assert_not_called()


@respx.mock
def test_download_aggtrades_writes_parquet_and_resumes(tmp_path: Path):
    # Binance returns up to 1000 trades per page, paginate by `fromId`.
    page1 = [
        {"a": i, "p": "100.0", "q": "0.5", "T": _ms(datetime(2025, 4, 1, 0, i // 60, i % 60)),
         "m": (i % 2 == 0)}
        for i in range(1000)
    ]
    page2 = [
        {"a": 1000 + i, "p": "100.0", "q": "0.5",
         "T": _ms(datetime(2025, 4, 1, 1, i // 60, i % 60)), "m": False}
        for i in range(50)
    ]
    page3: list = []  # empty → done

    route = respx.get("https://api.binance.com/api/v3/aggTrades").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
            httpx.Response(200, json=page3),
        ]
    )

    out = download_aggtrades(
        symbol="BTC/USDT",
        start=date(2025, 4, 1),
        end=date(2025, 4, 2),
        root=tmp_path,
    )
    assert out == aggtrades_parquet_path("BTC/USDT", root=tmp_path)
    df = pd.read_parquet(out)
    assert len(df) == 1050
    assert set(df.columns) == {"agg_id", "price", "qty", "ts", "is_buyer_maker"}
    assert df["agg_id"].is_monotonic_increasing
    assert route.call_count == 3


@respx.mock
def test_download_aggtrades_resumes_from_existing(tmp_path: Path):
    # Pre-seed an existing parquet so the downloader resumes from agg_id=500.
    seed = pd.DataFrame(
        {
            "agg_id": list(range(500)),
            "price": [100.0] * 500,
            "qty": [0.5] * 500,
            "ts": [_ms(datetime(2025, 4, 1)) + i * 1000 for i in range(500)],
            "is_buyer_maker": [False] * 500,
        }
    )
    path = aggtrades_parquet_path("BTC/USDT", root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    seed.to_parquet(path)

    page = [
        {"a": 500 + i, "p": "100.0", "q": "0.5",
         "T": _ms(datetime(2025, 4, 1, 0, 30)) + i, "m": False}
        for i in range(100)
    ]
    respx.get("https://api.binance.com/api/v3/aggTrades").mock(
        side_effect=[httpx.Response(200, json=page), httpx.Response(200, json=[])]
    )

    download_aggtrades(
        symbol="BTC/USDT", start=date(2025, 4, 1), end=date(2025, 4, 2), root=tmp_path
    )
    df = pd.read_parquet(path)
    assert len(df) == 600
    assert df["agg_id"].max() == 599
