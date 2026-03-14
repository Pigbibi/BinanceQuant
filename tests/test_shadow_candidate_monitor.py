import sys
import types
import unittest
from pathlib import Path

import pandas as pd


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
                raise RuntimeError("stub Firestore client should not be used in monitor unit tests")

            def set(self, *args, **kwargs):
                return None

        firestore_module.Client = FirestoreClient
        sys.modules["google.cloud.firestore"] = firestore_module
        sys.modules["google.cloud"].firestore = firestore_module


install_test_stubs()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run_shadow_candidate_monitor


class ShadowCandidateMonitorTests(unittest.TestCase):
    def test_validate_track_identity_accepts_expected_baseline_and_shadow_candidate(self):
        summary_table = pd.DataFrame(
            [
                {
                    "track_id": "official_baseline",
                    "track_profile": "baseline_blended_rank",
                    "source_track": "official_baseline",
                    "candidate_status": "official_reference",
                },
                {
                    "track_id": "challenger_topk_60",
                    "track_profile": "challenger_topk_60",
                    "source_track": "shadow_candidate",
                    "candidate_status": "shadow_candidate",
                },
            ]
        )

        run_shadow_candidate_monitor.validate_track_identity(summary_table)

    def test_validate_track_identity_rejects_shadow_candidate_marked_as_official(self):
        summary_table = pd.DataFrame(
            [
                {
                    "track_id": "official_baseline",
                    "track_profile": "baseline_blended_rank",
                    "source_track": "official_baseline",
                    "candidate_status": "official_reference",
                },
                {
                    "track_id": "challenger_topk_60",
                    "track_profile": "challenger_topk_60",
                    "source_track": "official_baseline",
                    "candidate_status": "official_reference",
                },
            ]
        )

        with self.assertRaises(ValueError):
            run_shadow_candidate_monitor.validate_track_identity(summary_table)


if __name__ == "__main__":
    unittest.main()
