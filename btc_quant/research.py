"""Predeclared pair selection: validation chooses ONE model, test never reselects."""
from __future__ import annotations
from pathlib import Path
import hashlib
import platform
import numpy as np
import pandas as pd
from .common import HOUR, utc, fingerprint, write_json, json_safe, read_json
from .signals import Candidate, generate_signals
from .backtest import run_backtest
from .evidence import metrics, validate_evidence


def select_candidate(records: list[dict], config: dict, baseline_sharpe: float) -> tuple[dict | None, dict | None]:
    """Validation records only. Returns (eligible winner, top research-only record)."""
    ordered = sorted(records, key=lambda r: (-r["daily_net_sharpe"], r["candidate"]))
    s = config["selection"]
    eligible = [r for r in ordered if r["trades"] >= s["min_validation_trades"]
        and r["mean_net_return"] is not None and r["mean_net_return"] > 0
        and r["profit_factor"] is not None and r["profit_factor"] >= s["min_validation_profit_factor"]
        and r["positive_month_fraction"] >= s["min_validation_positive_month_fraction"]
        and r["mean_stress_return"] is not None and r["mean_stress_return"] > 0
        and r["daily_net_sharpe"] > max(0.0, baseline_sharpe)]
    return (eligible[0] if eligible else None, ordered[0] if ordered else None)


def research(config: dict, prices: dict, funding: dict, output: Path, source: str = "real_exchange_archive") -> dict:
    output.mkdir(parents=True, exist_ok=True)
    d = config["data"]
    btc = prices[d["bitcoin"]]
    val_start, test_start, test_end = [utc(d[k]) for k in ("validation_start", "test_start", "end_exclusive")]
    records, baseline_records = [], []
    for family in ("breakout", "divergence"):
        cand = Candidate(family, None)
        events = generate_signals(btc.loc[btc.index < test_start], None, cand, config)
        tr, eq = run_backtest(btc, None, funding[d["bitcoin"]], None, cand, config, val_start, test_start, events)
        rec = {"candidate": cand.name, **cand.to_dict(), **metrics(tr, eq, val_start, test_start)}
        baseline_records.append(rec)
    baseline_sharpe = max(r["daily_net_sharpe"] for r in baseline_records)
    for peer_symbol in d["peers"]:
        peer = prices[peer_symbol]
        for family in config["signals"]["families"]:
            cand = Candidate(family, peer_symbol)
            # Holdout rows never enter selection-time signal construction.
            mask = btc.index < test_start
            events = generate_signals(btc.loc[mask], peer.loc[mask], cand, config)
            tr, eq = run_backtest(btc, peer, funding[d["bitcoin"]], funding[peer_symbol], cand, config, val_start, test_start, events)
            rec = {"candidate": cand.name, **cand.to_dict(), **metrics(tr, eq, val_start, test_start)}
            records.append(rec)
            folder = output / "validation_trades"; folder.mkdir(exist_ok=True)
            tr.to_csv(folder / f"{cand.name}.csv", index=False)
            print(f"VALIDATION {cand.name}: trades={rec['trades']} sharpe={rec['daily_net_sharpe']:.3f}", flush=True)
    pd.DataFrame(records).sort_values("daily_net_sharpe", ascending=False).to_csv(output / "pair_selection.csv", index=False)
    pd.DataFrame(baseline_records).to_csv(output / "btc_only_baselines.csv", index=False)
    winner, best = select_candidate(records, config, baseline_sharpe)
    # A research-only best candidate is examined, but cannot be promoted if validation failed.
    chosen = winner or best
    model = {"schema": 1, "version": config["version"], "fingerprint": fingerprint(config),
             "source": source, "created_at": str(pd.Timestamp.now(tz="UTC")),
             "validation_start": str(val_start), "test_start": str(test_start), "test_end_exclusive": str(test_end),
             "selection_trials": len(records), "selection_used_holdout": False,
             "selected": None, "approved": False, "validation_qualified": bool(winner),
             "best_is_only_relative_to_tested_candidates": True,
             "limitations": ["No individual-signal probability is calibrated.", "Fixed candidate list has survivorship/selection bias.",
                 "No order-book replay, liquidation model, broker fills or tax model.",
                 "Funding uses published rates and hourly open as mark-price proxy.",
                 "Close-marked drawdown understates possible intrabar drawdown.",
                 "Repeatedly tuning against this holdout invalidates its independence."]}
    if chosen:
        cand = Candidate(chosen["family"], chosen["peer"])
        model["selected"] = cand.to_dict()
        model["validation_metrics"] = chosen
        peer = prices[cand.peer]
        # Only the single validation-selected candidate is evaluated on holdout.
        events = generate_signals(btc, peer, cand, config)
        tr, eq = run_backtest(btc, peer, funding[d["bitcoin"]], funding[cand.peer], cand, config, test_start, test_end, events)
        tr.to_csv(output / "holdout_trades.csv", index=False)
        eq.to_csv(output / "holdout_equity.csv", index_label="time")
        evidence = validate_evidence(tr, eq, config, test_start, test_end, source)
        model["evidence"] = evidence
        model["approved"] = bool(winner) and evidence["approved"] and source == "real_exchange_archive"
        model["status"] = "HISTORICAL_EVIDENCE_PASSED" if model["approved"] else "NO_VALIDATED_90_PERCENT_EDGE"
        evidence["trade_ledger_sha256"] = hashlib.sha256((output / "holdout_trades.csv").read_bytes()).hexdigest()
        # Simple passive benchmark: BTC perpetual held across the test, including approximate funding/fees.
        from .backtest import funding_cashflow
        sample = btc.loc[(btc.index >= test_start) & (btc.index < test_end)]
        ep, xp = float(sample.open.iloc[0]), float(sample.close.iloc[-1])
        bh_f = funding_cashflow(funding[d["bitcoin"]], btc, sample.index[0], sample.index[-1]+HOUR-pd.Timedelta(nanoseconds=1), 1/ep)
        unitcost = (config["execution"]["fee_bps_per_side"]+config["execution"]["slippage_bps_per_side"])/10000
        write_json(output / "passive_benchmark.json", {"label": "BTC perpetual buy-and-hold, full gross exposure; NOT risk-matched to hedged pairs",
            "net_return": xp/ep-1+bh_f-unitcost*(1+xp/ep)})
    else:
        model["status"] = "NO_VALIDATION_CANDIDATE"
    write_json(output / "model.json", model)
    write_json(output / "run_environment.json", {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__, "source": source})
    report = render_report(model, records, baseline_records, config)
    (output / "BACKTEST_REPORT.md").write_text(report, encoding="utf-8")
    return model


def render_report(model, records, baselines, config):
    lines = ["# BTC Quant Bot 2 - research report", "", f"Status: **{model['status']}**", f"Data source: `{model['source']}`", "",
             "This report is not a promise of a >90% next-trade win probability.",
             "One winner is chosen on validation; holdout is not used to select a replacement.", "",
             f"Validation: {model['validation_start']} to {model['test_start']} (exclusive).",
             f"Holdout: {model['test_start']} to {model['test_end_exclusive']} (exclusive).", "",
             "## Validation comparison", "", "| Candidate | Trades | Net win rate | Mean net/trade | Daily Sharpe | Profit factor |", "|---|---:|---:|---:|---:|---:|"]
    for r in sorted(records, key=lambda x: x["daily_net_sharpe"], reverse=True):
        win = f"{r['win_rate']:.1%}" if r["win_rate"] is not None else "N/A"
        avg = f"{r['mean_net_return']:.3%}" if r["mean_net_return"] is not None else "N/A"
        pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] is not None else "N/A"
        lines.append(f"| {r['candidate']} | {r['trades']} | {win} | {avg} | {r['daily_net_sharpe']:.2f} | {pf} |")
    if model.get("selected"):
        lines += ["", "## Single selected holdout", f"Candidate: `{model['selected']['id']}`", f"Passed validation admission: {model['validation_qualified']}", ""]
        m = model["evidence"]["test_metrics"]
        for k in ("trades", "wins", "win_rate", "mean_net_return", "mean_win", "mean_loss", "profit_factor", "total_return", "daily_net_sharpe", "max_drawdown_close_mtm", "mean_stress_return"):
            if k in m: lines.append(f"- {k}: {m[k]}")
        lines += ["", "## Strict evidence gate", "", "| Subset | Wins / trades | Wilson lower | Block lower | Passed |", "|---|---:|---:|---:|---|"]
        for k, row in model["evidence"]["subsets"].items():
            lines.append(f"| {k} | {row['wins']} / {row['trades']} | {row['wilson_lower']:.1%} | {row['block_win_lower']:.1%} | {row['passed']} |")
        lines += ["", "Rejection reasons:", *[f"- {r}" for r in model["evidence"]["reasons"]]]
    lines += ["", "## Execution assumptions", "",
        "Closed 1h signal; entry at the NEXT hourly open after the notification hour (one full-hour delay after signal close).",
        "One position/pair at a time; gross exposure 1.0, no pyramiding, no martingale, no average-down.",
        f"Fee {config['execution']['fee_bps_per_side']} bp + slippage {config['execution']['slippage_bps_per_side']} bp per side of traded notional; all legs charged.",
        "Published funding rates included, using hourly open instead of unavailable exact historical mark price.",
        "Directional TP/SL are simulated as native orders: stop-first if both occur in the same candle.",
        "Pair exits are close-based, delayed one further full hour; not intrabar risk stops.",
        "End-of-window entry embargo prevents excluding unresolved losses. Flat hours are retained for daily Sharpe.",
        "Cost stress doubles fee + slippage only; it is not a worst-case gap/liquidity stress.", "",
        "## Limitations", *[f"- {r}" for r in model["limitations"]], "",
        "Tests of program logic or synthetic series do not demonstrate a market edge."]
    return "\n".join(lines)+"\n"
