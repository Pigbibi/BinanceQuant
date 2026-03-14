#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import run_challenger_robustness as robustness
import shadow_replay


DEFAULT_UPSTREAM_ROOT = Path(__file__).resolve().parents[1] / "CryptoLeaderRotation"
DEFAULT_TRACKS = {
    "official_baseline": Path("data/output/shadow_candidate_tracks/official_baseline/release_index.csv"),
    "challenger_topk_60": Path("data/output/shadow_candidate_tracks/challenger_topk_60/release_index.csv"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run baseline vs challenger_topk_60 dual-track shadow monitoring.")
    parser.add_argument("--upstream-root", default=str(DEFAULT_UPSTREAM_ROOT), help="Path to the CryptoLeaderRotation repo.")
    parser.add_argument("--output-dir", default="reports", help="Directory for shadow monitor outputs.")
    parser.add_argument("--raw-dir", default=None, help="Optional override for local daily raw OHLCV CSVs.")
    parser.add_argument("--max-age-days", type=int, default=45, help="Freshness window used for both tracks.")
    parser.add_argument("--activation-lag-days", type=int, default=None, help="Optional shared activation lag override.")
    parser.add_argument("--cost-bps", type=float, default=0.0, help="Optional shared turnover-scaled cost assumption.")
    return parser.parse_args()


def validate_track_identity(summary_table: pd.DataFrame) -> None:
    required = {
        "official_baseline": ("baseline_blended_rank", "official_baseline", "official_reference"),
        "challenger_topk_60": ("challenger_topk_60", "shadow_candidate", "shadow_candidate"),
    }
    rows = summary_table.set_index("track_id")
    for track_id, (profile, source_track, candidate_status) in required.items():
        if track_id not in rows.index:
            raise ValueError(f"Missing required track: {track_id}")
        row = rows.loc[track_id]
        if str(row.get("track_profile", "")) != profile:
            raise ValueError(f"Track {track_id} has unexpected profile: {row.get('track_profile')}")
        if str(row.get("source_track", "")) != source_track:
            raise ValueError(f"Track {track_id} has unexpected source_track: {row.get('source_track')}")
        if str(row.get("candidate_status", "")) != candidate_status:
            raise ValueError(f"Track {track_id} has unexpected candidate_status: {row.get('candidate_status')}")


def build_side_by_side_summary(summary_table: pd.DataFrame) -> pd.DataFrame:
    baseline = summary_table.loc[summary_table["track_id"] == "official_baseline"].iloc[0]
    challenger = summary_table.loc[summary_table["track_id"] == "challenger_topk_60"].iloc[0]
    return pd.DataFrame(
        [
            {
                "baseline_profile": baseline["track_profile"],
                "challenger_profile": challenger["track_profile"],
                "baseline_source_track": baseline["source_track"],
                "challenger_source_track": challenger["source_track"],
                "baseline_candidate_status": baseline["candidate_status"],
                "challenger_candidate_status": challenger["candidate_status"],
                "baseline_cagr": baseline["CAGR"],
                "challenger_cagr": challenger["CAGR"],
                "delta_cagr": challenger["CAGR"] - baseline["CAGR"],
                "baseline_sharpe": baseline["Sharpe"],
                "challenger_sharpe": challenger["Sharpe"],
                "delta_sharpe": challenger["Sharpe"] - baseline["Sharpe"],
                "baseline_max_drawdown": baseline["Max Drawdown"],
                "challenger_max_drawdown": challenger["Max Drawdown"],
                "delta_max_drawdown": challenger["Max Drawdown"] - baseline["Max Drawdown"],
                "baseline_turnover": baseline["Turnover"],
                "challenger_turnover": challenger["Turnover"],
                "delta_turnover": challenger["Turnover"] - baseline["Turnover"],
            }
        ]
    )


def build_promotion_watchlist(
    monthly_excess: pd.DataFrame,
    concentration: pd.DataFrame,
    regime_summary: pd.DataFrame,
    release_summary: pd.DataFrame,
) -> pd.DataFrame:
    excess_column = "challenger_topk_60_excess_vs_baseline"
    recent_12 = monthly_excess.tail(12).copy()
    recent_6 = monthly_excess.tail(6).copy()
    prior_12 = monthly_excess.iloc[-24:-12].copy() if len(monthly_excess) >= 24 else pd.DataFrame()

    concentration_row = concentration.loc[concentration["profile"] == "challenger_topk_60"].iloc[0]

    release_pivot = release_summary.pivot(index="release_as_of_date", columns="profile", values="net_return").sort_index()
    release_pivot["excess_vs_baseline"] = (
        release_pivot.get("challenger_topk_60", 0.0) - release_pivot.get("baseline_blended_rank", 0.0)
    )
    recent_release_window = release_pivot.tail(6)

    regime_pivot = regime_summary.pivot(index="release_regime", columns="profile", values="net_return")
    risk_off_excess = (
        float(regime_pivot.loc["risk_off", "challenger_topk_60"] - regime_pivot.loc["risk_off", "baseline_blended_rank"])
        if "risk_off" in regime_pivot.index
        else float("nan")
    )

    return pd.DataFrame(
        [
            {
                "recent_12_month_outperformance_rate": float((recent_12[excess_column] > 0).mean()) if not recent_12.empty else float("nan"),
                "recent_6_month_outperformance_rate": float((recent_6[excess_column] > 0).mean()) if not recent_6.empty else float("nan"),
                "recent_12_month_mean_excess": float(recent_12[excess_column].mean()) if not recent_12.empty else float("nan"),
                "prior_12_month_mean_excess": float(prior_12[excess_column].mean()) if not prior_12.empty else float("nan"),
                "recent_6_release_total_excess": float(recent_release_window["excess_vs_baseline"].sum()) if not recent_release_window.empty else float("nan"),
                "top_5_positive_excess_share": float(concentration_row["top_5_positive_excess_share"]),
                "risk_off_excess_vs_baseline": risk_off_excess,
                "gate_recent_12_positive": bool(not recent_12.empty and recent_12[excess_column].sum() > 0),
                "gate_recent_6_releases_positive": bool(not recent_release_window.empty and recent_release_window["excess_vs_baseline"].sum() > 0),
                "gate_concentration_not_extreme": bool(float(concentration_row["top_5_positive_excess_share"]) <= 0.70),
                "gate_risk_off_not_worse": bool(pd.notna(risk_off_excess) and risk_off_excess >= 0.0),
            }
        ]
    )


def main() -> None:
    args = parse_args()
    upstream_root = Path(args.upstream_root).resolve()
    raw_dir = Path(args.raw_dir).resolve() if args.raw_dir else upstream_root / "data" / "raw"
    output_dir = shadow_replay.ensure_directory(args.output_dir)

    summaries = []
    details = []
    for track_id, relative_path in DEFAULT_TRACKS.items():
        release_index_path = upstream_root / relative_path
        summary, detail = shadow_replay.run_shadow_replay(
            release_index_path=release_index_path,
            artifacts_root=release_index_path.parent,
            raw_dir=raw_dir,
            max_age_days=max(0, int(args.max_age_days)),
            activation_lag_days=args.activation_lag_days,
            cost_bps=float(args.cost_bps),
        )
        summary = summary.copy()
        summary["track_id"] = track_id
        detail = detail.copy()
        detail["track_id"] = track_id
        summaries.append(summary)
        details.append(detail)

    summary_table = pd.concat(summaries, ignore_index=True)
    detail_table = pd.concat(details, ignore_index=True)
    validate_track_identity(summary_table)

    summary_path = output_dir / "shadow_candidate_track_summary.csv"
    side_by_side_path = output_dir / "shadow_candidate_side_by_side_summary.csv"
    detail_path = output_dir / "shadow_candidate_detail.csv"
    monthly_path = output_dir / "shadow_candidate_monthly_returns.csv"
    monthly_vs_baseline_path = output_dir / "shadow_candidate_monthly_vs_baseline.csv"
    regime_path = output_dir / "shadow_candidate_regime_summary.csv"
    release_path = output_dir / "shadow_candidate_release_period.csv"
    concentration_path = output_dir / "shadow_candidate_concentration_summary.csv"
    watchlist_path = output_dir / "shadow_candidate_promotion_watchlist.csv"

    summary_table.to_csv(summary_path, index=False)
    build_side_by_side_summary(summary_table).to_csv(side_by_side_path, index=False)
    detail_table.to_csv(detail_path, index=False)

    monthly_table = robustness.build_monthly_comparison(detail_table)
    monthly_table.to_csv(monthly_path, index=False)
    monthly_excess = robustness.build_excess_table(monthly_table)
    monthly_excess.to_csv(monthly_vs_baseline_path, index=False)
    concentration = robustness.build_excess_concentration(monthly_excess)
    concentration.to_csv(concentration_path, index=False)

    regime_summary = robustness.summarize_detail(
        detail_table.loc[detail_table["release_regime"].notna()].copy(),
        ["profile", "release_regime"],
    )
    release_summary = robustness.summarize_detail(
        detail_table,
        ["profile", "release_version", "release_as_of_date", "release_regime"],
    )
    regime_summary.to_csv(regime_path, index=False)
    release_summary.to_csv(release_path, index=False)
    build_promotion_watchlist(monthly_excess, concentration, regime_summary, release_summary).to_csv(
        watchlist_path,
        index=False,
    )

    print(summary_table.to_string(index=False))
    print(f"summary_path={summary_path}")
    print(f"side_by_side_path={side_by_side_path}")
    print(f"detail_path={detail_path}")
    print(f"monthly_path={monthly_path}")
    print(f"monthly_vs_baseline_path={monthly_vs_baseline_path}")
    print(f"regime_path={regime_path}")
    print(f"release_path={release_path}")
    print(f"concentration_path={concentration_path}")
    print(f"watchlist_path={watchlist_path}")


if __name__ == "__main__":
    main()
