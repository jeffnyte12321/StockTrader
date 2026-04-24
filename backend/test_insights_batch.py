import unittest
from unittest.mock import patch

import pandas as pd

import main


def _series(start_value: float, count: int = 45, step: float = 1.0) -> pd.Series:
    dates = pd.date_range("2026-01-02", periods=count, freq="B")
    values = [start_value + (step * idx) for idx in range(count)]
    return pd.Series(values, index=dates, dtype="float64")


def _price_map(series: pd.Series) -> dict:
    return {pd.Timestamp(idx).date(): float(value) for idx, value in series.items()}


class InsightsBatchTests(unittest.TestCase):
    def test_batch_analysis_uses_cached_closes_and_single_download_result(self):
        aapl_close = _series(100.0)
        msft_close = _series(200.0, step=0.8)
        fake_cache = {
            "AAPL": _price_map(aapl_close),
            "MSFT": _price_map(msft_close),
        }
        fake_download = {
            "AAPL": {"close": aapl_close, "volume": _series(1_000_000.0, step=10_000.0), "source": "yfinance"},
            "MSFT": {"close": msft_close, "volume": _series(900_000.0, step=8_000.0), "source": "yfinance"},
        }

        with patch.object(main, "_get_cached_price_history", return_value=fake_cache) as cache_mock, \
             patch.object(main, "_download_insight_market_data", return_value=fake_download) as download_mock, \
             patch.object(main.db, "upsert_price_history_rows") as upsert_mock, \
             patch.object(main.db, "SUPABASE_SERVICE_ROLE_KEY", "service-role"):
            results = main._analyze_stocks_batch("token", ["AAPL", "MSFT"])

        self.assertEqual({result["symbol"] for result in results}, {"AAPL", "MSFT"})
        cache_mock.assert_called_once()
        download_mock.assert_called_once()
        upsert_mock.assert_not_called()

    def test_batch_analysis_caches_uncached_downloaded_closes_when_service_role_exists(self):
        aapl_close = _series(150.0, step=0.5)
        fake_download = {
            "AAPL": {"close": aapl_close, "volume": _series(1_200_000.0, step=12_000.0), "source": "yfinance"},
        }

        with patch.object(main, "_get_cached_price_history", return_value={}) as cache_mock, \
             patch.object(main, "_download_insight_market_data", return_value=fake_download) as download_mock, \
             patch.object(main.db, "upsert_price_history_rows") as upsert_mock, \
             patch.object(main.db, "SUPABASE_SERVICE_ROLE_KEY", "service-role"):
            results = main._analyze_stocks_batch("token", ["AAPL"])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["symbol"], "AAPL")
        cache_mock.assert_called_once()
        download_mock.assert_called_once()
        upsert_mock.assert_called_once()
        cached_rows = upsert_mock.call_args.args[0]
        self.assertTrue(cached_rows)
        self.assertTrue(all(row["symbol"] == "AAPL" for row in cached_rows))
        self.assertEqual(upsert_mock.call_args.kwargs, {"use_service_role": True})


if __name__ == "__main__":
    unittest.main()
