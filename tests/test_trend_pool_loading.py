import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


def install_test_stubs():
    if "binance" not in sys.modules:
        binance_module = types.ModuleType("binance")
        client_module = types.ModuleType("binance.client")
        exceptions_module = types.ModuleType("binance.exceptions")

        class Client:
            KLINE_INTERVAL_1DAY = "1d"

            def __init__(self, *args, **kwargs):
                pass

            def ping(self):
                return None

        class BinanceAPIException(Exception):
            pass

        client_module.Client = Client
        exceptions_module.BinanceAPIException = BinanceAPIException
        binance_module.client = client_module
        binance_module.exceptions = exceptions_module
        sys.modules["binance"] = binance_module
        sys.modules["binance.client"] = client_module
        sys.modules["binance.exceptions"] = exceptions_module

    if "google" not in sys.modules:
        sys.modules["google"] = types.ModuleType("google")
    if "google.cloud" not in sys.modules:
        cloud_module = types.ModuleType("google.cloud")
        sys.modules["google.cloud"] = cloud_module
        sys.modules["google"].cloud = cloud_module
    if "google.cloud.firestore" not in sys.modules:
        firestore_module = types.ModuleType("google.cloud.firestore")

        class FirestoreClient:
            def collection(self, *args, **kwargs):
                return self

            def document(self, *args, **kwargs):
                return self

            def get(self):
                raise RuntimeError("stub Firestore client should be patched in unit tests")

            def set(self, *args, **kwargs):
                return None

        firestore_module.Client = FirestoreClient
        sys.modules["google.cloud.firestore"] = firestore_module
        sys.modules["google.cloud"].firestore = firestore_module


install_test_stubs()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main


def build_payload(as_of_date="2026-03-10", *, mode="core_major"):
    symbol_map = {
        "ETHUSDT": {"base_asset": "ETH"},
        "SOLUSDT": {"base_asset": "SOL"},
        "XRPUSDT": {"base_asset": "XRP"},
        "LTCUSDT": {"base_asset": "LTC"},
        "BCHUSDT": {"base_asset": "BCH"},
    }
    return {
        "as_of_date": as_of_date,
        "version": f"{as_of_date}-{mode}",
        "mode": mode,
        "pool_size": len(symbol_map),
        "symbols": list(symbol_map.keys()),
        "symbol_map": symbol_map,
        "source_project": "crypto-leader-rotation",
    }


class TrendPoolLoadingTests(unittest.TestCase):
    def test_validate_trend_pool_payload_rejects_stale_payload(self):
        payload = build_payload(as_of_date="2026-01-01")

        result = main.validate_trend_pool_payload(
            payload,
            source_label="test",
            now_utc=datetime(2026, 3, 14, tzinfo=timezone.utc),
            max_age_days=30,
            acceptable_modes=["core_major"],
            expected_pool_size=5,
            enforce_freshness=True,
        )

        self.assertFalse(result["ok"])
        self.assertIn("stale", " ".join(result["errors"]))

    def test_resolve_trend_pool_source_prefers_last_known_good_before_local_file(self):
        last_good_payload = build_payload(as_of_date="2026-02-15")
        file_result = main.validate_trend_pool_payload(
            build_payload(as_of_date="2026-03-12"),
            source_label="file:/tmp/live_pool_legacy.json",
            now_utc=datetime(2026, 3, 14, tzinfo=timezone.utc),
            acceptable_modes=["core_major"],
            expected_pool_size=5,
            enforce_freshness=True,
        )

        with patch.object(
            main,
            "load_trend_pool_from_firestore",
            return_value={"ok": False, "errors": ["payload stale"], "warnings": [], "source_label": "firestore:test"},
        ), patch.object(main, "load_trend_pool_from_file", return_value=file_result), patch.object(
            main,
            "get_default_live_pool_candidates",
            return_value=[Path("/tmp/live_pool_legacy.json")],
        ):
            resolution = main.resolve_trend_pool_source(
                state={main.TREND_POOL_LAST_GOOD_PAYLOAD_KEY: last_good_payload},
                now_utc=datetime(2026, 3, 14, tzinfo=timezone.utc),
            )

        self.assertEqual(resolution["source_kind"], "last_known_good")
        self.assertTrue(resolution["degraded"])
        self.assertEqual(resolution["version"], "2026-02-15-core_major")

    def test_update_trend_pool_state_persists_metadata_and_last_good_payload(self):
        validated = main.validate_trend_pool_payload(
            build_payload(),
            source_label="firestore:strategy/CRYPTO_LEADER_ROTATION_LIVE_POOL",
            now_utc=datetime(2026, 3, 14, tzinfo=timezone.utc),
            acceptable_modes=["core_major"],
            expected_pool_size=5,
            enforce_freshness=True,
        )
        resolution = main.build_trend_pool_resolution(
            validated,
            source_kind="fresh_upstream",
            degraded=False,
            now_utc=datetime(2026, 3, 14, tzinfo=timezone.utc),
        )
        state = main.build_default_state()

        main.update_trend_pool_state(state, resolution)

        self.assertEqual(state["trend_pool_source"], "fresh_upstream")
        self.assertEqual(state["trend_pool_version"], "2026-03-10-core_major")
        self.assertEqual(state["trend_pool_mode"], "core_major")
        self.assertEqual(state["trend_pool_source_project"], "crypto-leader-rotation")
        self.assertEqual(
            state[main.TREND_POOL_LAST_GOOD_PAYLOAD_KEY]["version"],
            "2026-03-10-core_major",
        )

    def test_duplicate_trend_action_guard(self):
        state = main.build_default_state()

        self.assertFalse(main.should_skip_duplicate_trend_action(state, "ETHUSDT", "buy", "20260314"))
        main.record_trend_action(state, "ETHUSDT", "buy", "20260314")
        self.assertTrue(main.should_skip_duplicate_trend_action(state, "ETHUSDT", "buy", "20260314"))
        self.assertFalse(main.should_skip_duplicate_trend_action(state, "ETHUSDT", "sell", "20260314"))


if __name__ == "__main__":
    unittest.main()
