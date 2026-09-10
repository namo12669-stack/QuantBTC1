"""Predeclared candidate selection: validation chooses one model, holdout never reselects."""
from __future__ import annotations

import hashlib
import platform
from pathlib import Path

import numpy as np
import pandas as pd

from .common import HOUR, utc, fingerprint, write_json
from .signals import Candidate, generate_signals
from .backtest import run_backtest
from .evidence import metrics, validate_evidence

REAL_SOURCE = "real_coinbase_spot_api"


def select_candidate(records: list[dict], config: dict, baseline_sharpe: float) -> tuple[dict | None, dict | None]:
    ordered = sorted(records, key=lambda r: (-r["daily_net_sharpe"], r["candidate"]))
    s = config["selection"]
    eligible = [
        r for r in ordered
        if r["trades"] >= s["min_validation_trades"]
        and r["mean_net_return"] is not None and r["mean_net_return"] > 0
        and r["profit_factor"] is not None and r["profit_factor"] >= s["min_validation_profit_factor"]
        and r["positive_month_fraction"] >= s["min_validation_positive_month_fraction"]
        and r["mean_stress_return"] is not None and r["mean_stress_return"] > 0
        and r["daily_net_sharpe"] > max(0.0, baseline_sharpe)
    ]
    return (eligible[0] if eligible else None, ordered[0] if ordered else None)


def _empty_funding(prices: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(columns=["rate"], index=pd.DatetimeIndex([], tz="UTC", name="time"))


def research(config: dict, prices: dict, funding: dict, output: Path, source: str = REAL_SOURCE) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    d = config["data"]
    btc = prices[d["bitcoin"]]
    val_start, test_start, test_end = [utc(d[k]) for k in ("validation_start", "test_start", "end_exclusive")]
    records, baseline_records = [], []
    nofund = _empty_funding(btc)

    # BTC-only baselines tell us whether a peer actually adds value.
    for family in ("breakout", "divergence"):
        cand = Candidate(family, None)
        events = generate_signals(btc.loc[btc.index < test_start], None, cand, config)
        tr, eq = run_backtest(btc, None, nofund, None, cand, config, val_start, test_start, events)
        baseline_records.append({"candidate": cand.name, **cand.to_dict(), **metrics(tr, eq, val_start, test_start)})
    baseline_sharpe = max((r["daily_net_sharpe"] for r in baseline_records), default=0.0)

    for peer_symbol in d["peers"]:
        peer = prices[peer_symbol]
        for family in config["signals"]["families"]:
            cand = Candidate(family, peer_symbol)
            mask = btc.index < test_start
            events = generate_signals(btc.loc[mask], peer.loc[mask], cand, config)
            tr, eq = run_backtest(btc, peer, nofund, nofund, cand, config, val_start, test_start, events)
            rec = {"candidate": cand.name, **cand.to_dict(), **metrics(tr, eq, val_start, test_start)}
            records.append(rec)
            folder = output / "validation_trades"
            folder.mkdir(exist_ok=True)
            tr.to_csv(folder / f"{cand.name}.csv", index=False)
            print(f"VALIDATION {cand.name}: trades={rec['trades']} sharpe={rec['daily_net_sharpe']:.3f}", flush=True)

    pd.DataFrame(records).sort_values("daily_net_sharpe", ascending=False).to_csv(output / "pair_selection.csv", index=False)
    pd.DataFrame(baseline_records).to_csv(output / "btc_only_baselines.csv", index=False)
    winner, best = select_candidate(records, config, baseline_sharpe)
    chosen = winner or best
    threshold = float(config["proof_gate"]["minimum_win_rate_lower_bound"])

    data_quality = {
        symbol: frame.attrs.get("gap_summary", {"missing_bars": 0, "missing_fraction": 0.0, "max_consecutive_missing_hours": 0})
        for symbol, frame in prices.items()
    }

    model = {
        "schema": 3,
        "version": config["version"],
        "fingerprint": fingerprint(config),
        "source": source,
        "venue": d["venue"],
        "created_at": str(pd.Timestamp.now(tz="UTC")),
        "validation_start": str(val_start),
        "test_start": str(test_start),
        "test_end_exclusive": str(test_end),
        "selection_trials": len(records),
        "selection_used_holdout": False,
        "selected": None,
        "approved": False,
        "validation_qualified": bool(winner),
        "best_is_only_relative_to_tested_candidates": True,
        "historical_lower_bound_target": threshold,
        "trade_expression": "BTC_DIRECTION_ONLY; peer is signal context, not a required hedge leg",
        "data_quality": data_quality,
        "limitations": [
            "No individual-signal probability is calibrated.",
            "Fixed peer list has survivorship and researcher-selection bias.",
            "No order-book replay, broker fills, short-borrow cost, tax, liquidation or leverage model.",
            "Coinbase public candle history has no provider-supplied archive checksum; normalized CSV hashes are stored locally.",
            "SELL means a hypothetical BTC short; spot short availability/borrow is not modeled.",
            "Close-marked drawdown understates possible intrabar drawdown.",
            "Repeated tuning against this holdout invalidates its independence.",
            "Missing provider candles are never forward-filled; rolling models restart after gaps and unmeasurable trades crossing gaps are excluded and disclosed.",
        ],
    }

    if chosen:
        cand = Candidate(chosen["family"], chosen["peer"])
        model["selected"] = cand.to_dict()
        model["validation_metrics"] = chosen
        peer = prices[cand.peer]
        events = generate_signals(btc, peer, cand, config)
        tr, eq = run_backtest(btc, peer, nofund, nofund, cand, config, test_start, test_end, events)
        tr.to_csv(output / "holdout_trades.csv", index=False)
        eq.to_csv(output / "holdout_equity.csv", index_label="time")
        evidence = validate_evidence(tr, eq, config, test_start, test_end, source)
        model["evidence"] = evidence
        model["approved"] = bool(winner) and evidence["approved"] and source == REAL_SOURCE
        pct = int(round(threshold * 100))
        model["status"] = "HISTORICAL_EVIDENCE_PASSED" if model["approved"] else f"NO_VALIDATED_{pct}_PERCENT_EDGE"
        evidence["trade_ledger_sha256"] = hashlib.sha256((output / "holdout_trades.csv").read_bytes()).hexdigest()

        sample = btc.loc[(btc.index >= test_start) & (btc.index < test_end)].dropna(subset=["open", "close"])
        if sample.empty:
            raise ValueError("No complete BTC observations for passive benchmark")
        ep, xp = float(sample.open.iloc[0]), float(sample.close.iloc[-1])
        unitcost = (config["execution"]["fee_bps_per_side"] + config["execution"]["slippage_bps_per_side"]) / 10000.0
        write_json(output / "passive_benchmark.json", {
            "label": "BTC-USD Coinbase spot buy-and-hold; not risk-matched to signal strategies",
            "net_return": xp / ep - 1 - unitcost * (1 + xp / ep),
        })
    else:
        model["status"] = "NO_VALIDATION_CANDIDATE"

    write_json(output / "model.json", model)
    write_json(output / "run_environment.json", {
        "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__, "source": source,
    })
    (output / "BACKTEST_REPORT.md").write_text(render_report(model, records, baseline_records, config), encoding="utf-8")
    return model


def render_report(model, records, baselines, config):
    threshold = float(config["proof_gate"]["minimum_win_rate_lower_bound"])
    pct = int(round(threshold * 100))
    lines = [
        "# BTC Quant Bot 2 v1.1.2 - research report", "",
        f"Status: **{model['status']}**",
        f"Data source: `{model['source']}` / venue `{config['data']['venue']}`", "",
        f"The strict gate targets a conservative historical net-win-rate lower bound above {pct}%.",
        "It is NOT an estimate that the next trade has that probability of winning.",
        "One winner is chosen on validation; holdout is not used to select a replacement.", "",
        f"Validation: {model['validation_start']} to {model['test_start']} (exclusive).",
        f"Holdout: {model['test_start']} to {model['test_end_exclusive']} (exclusive).", "",
        "## Data quality / missing-hour policy", "",
        "Missing candles are never forward-filled. Models restart after gaps; trades whose evaluation window crosses a missing BTC candle are excluded as unmeasurable.",
        "",
        "| Symbol | Missing bars | Missing fraction | Longest gap |",
        "|---|---:|---:|---:|",
        *[f"| {sym} | {q.get('missing_bars',0)} | {q.get('missing_fraction',0):.3%} | {q.get('max_consecutive_missing_hours',0)}h |" for sym,q in model.get('data_quality',{}).items()],
        "",
        "## Validation comparison", "",
        "| Candidate | Trades | Net win rate | Mean net/trade | Daily Sharpe | Profit factor |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(records, key=lambda x: x["daily_net_sharpe"], reverse=True):
        win = f"{r['win_rate']:.1%}" if r["win_rate"] is not None else "N/A"
        avg = f"{r['mean_net_return']:.3%}" if r["mean_net_return"] is not None else "N/A"
        pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] is not None and np.isfinite(r["profit_factor"]) else "inf/N/A"
        lines.append(f"| {r['candidate']} | {r['trades']} | {win} | {avg} | {r['daily_net_sharpe']:.2f} | {pf} |")

    if model.get("selected") and model.get("evidence"):
        lines += ["", "## Single selected holdout", f"Candidate: `{model['selected']['id']}`",
                  f"Passed validation admission: {model['validation_qualified']}", ""]
        m = model["evidence"]["test_metrics"]
        for k in ("trades", "wins", "win_rate", "mean_net_return", "mean_win", "mean_loss", "profit_factor", "total_return",
                  "daily_net_sharpe", "max_drawdown_close_mtm", "mean_stress_return"):
            if k in m:
                lines.append(f"- {k}: {m[k]}")
        lines += ["", "## Strict evidence gate", "",
                  "| Subset | Wins / trades | Wilson lower | Block lower | Passed |",
                  "|---|---:|---:|---:|---|"]
        for k, row in model["evidence"]["subsets"].items():
            lines.append(f"| {k} | {row['wins']} / {row['trades']} | {row['wilson_lower']:.1%} | {row['block_win_lower']:.1%} | {row['passed']} |")
        lines += ["", "Rejection reasons:", *[f"- {r}" for r in model["evidence"]["reasons"]]]

    lines += ["", "## Execution assumptions", "",
              "Closed 1h signal; simulated entry is delayed until the next full hourly open after the notification hour.",
              "Every candidate trades BTC direction only. Companion assets are signal context, not required hedge legs.",
              f"Fee {config['execution']['fee_bps_per_side']} bp + slippage {config['execution']['slippage_bps_per_side']} bp per side of BTC notional.",
              "No funding is included because v1.1.2 uses Coinbase spot market data.",
              "Directional TP/SL use a conservative stop-first assumption if both are touched in one candle.",
              "End-of-window entry embargo prevents unresolved trades being omitted.",
              "Cost stress doubles fee + slippage only; it is not a worst-case liquidity stress.", "",
              "## Limitations", *[f"- {r}" for r in model["limitations"]], "",
              "Passing software tests does not demonstrate a market edge."]
    return "\n".join(lines) + "\n"
