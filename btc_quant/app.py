from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from .common import ROOT, HOUR, utc, write_json, load_config, fingerprint, DataError
from .data import download_history, load_history, live_history, PublicClient, API, fetch_candles, fetch_book
from .signals import Candidate, generate_signals
from .research import research, REAL_SOURCE
from .store import Store
from . import telegram
from .backtest import directional_rules
from .monitor import make_position, monitor_position


def eligibility(model: dict | None, config: dict, now) -> tuple[bool, list[str]]:
    if not model:
        return False, ["NO_BACKTEST_MODEL: run Research Backtest first"]
    reasons = []
    threshold = float(config["proof_gate"]["minimum_win_rate_lower_bound"])
    pct = int(round(threshold * 100))
    if model.get("source") != REAL_SOURCE:
        reasons.append("REAL_COINBASE_SPOT_EVIDENCE_REQUIRED")
    if model.get("fingerprint") != fingerprint(config):
        reasons.append("CODE_OR_CONFIG_CHANGED: rerun research")
    if not model.get("approved") or not model.get("evidence", {}).get("approved"):
        reasons.append(f"{pct}_PERCENT_HISTORICAL_EVIDENCE_NOT_PASSED")
    end = model.get("test_end_exclusive")
    if not end or utc(now) - utc(end) > pd.Timedelta(days=config["proof_gate"]["max_evidence_age_days"]):
        reasons.append("BACKTEST_EVIDENCE_STALE")
    if end and utc(end) > utc(now):
        reasons.append("FUTURE_TEST_END_INVALID")
    return not reasons, reasons


def status_message(model, reasons, config=None):
    selected = model.get("selected") if model else None
    threshold = float((config or {}).get("proof_gate", {}).get("minimum_win_rate_lower_bound", 0.80))
    pct = int(round(threshold * 100))
    text = [
        "BTC QUANT BOT 2 v1.1.1 | 1H | COINBASE SPOT",
        "STATUS: NO APPROVED ENTRY" if reasons else "STATUS: HISTORICAL EVIDENCE GATE PASSED",
        f"Candidate: {selected['id'] if selected else 'not selected - research not completed'}",
    ]
    if reasons:
        text.extend(reasons)
    if model and model.get("evidence"):
        ev = model["evidence"]["subsets"].get("overall", {})
        if ev.get("trades"):
            text.append(
                f"Holdout: {ev['wins']}/{ev['trades']} net winners; conservative historical lower bound "
                f"{ev['evidence_lower_bound']:.1%}"
            )
    text.extend([
        f"Gate target: historical lower bound > {pct}%, NOT a forecast that the next trade wins {pct}% of the time.",
        "No per-signal probability is calibrated. No profit guarantee.",
        "No order placed. Paper mode is research-only and manual.",
    ])
    return "\n".join(text)


def entry_message(signal, model, config, mode):
    entry = signal.time + HOUR * config["execution"]["entry_delay_bars"]
    threshold = int(round(float(config["proof_gate"]["minimum_win_rate_lower_bound"]) * 100))
    lines = [
        "BTC QUANT BOT 2 v1.1.1 | CLOSED 1H | COINBASE SPOT DATA",
        f"PAPER ONLY - {threshold}% HISTORICAL GATE NOT REQUIRED" if mode == "paper" else "HISTORICAL EVIDENCE GATE PASSED - NOT A GUARANTEE",
        f"BTC: {signal.label} ({'LONG' if signal.direction > 0 else 'SHORT'})",
        f"Signal: {signal.family}",
        f"Companion/context: {signal.peer or 'BTC only'}",
        f"Confirmed at: {signal.time + HOUR}",
        f"Planned model entry: {entry} (next full hourly open)",
    ]
    if signal.family == "pair_spread":
        lines += [
            "PAIR RELATIONSHIP USED AS BTC DIRECTION CONTEXT - NO COMPANION ORDER IS MODELED.",
            f"Spread z: {signal.details.get('z_now', float('nan')):.2f}; beta: {signal.beta:.3f}; "
            f"formation cointegration p: {signal.details.get('cointegration_p', float('nan')):.4f}",
        ]
    sl, tp, hold = directional_rules(signal.family, config)
    lines += [
        f"ATR at signal: {signal.atr:.2f} USD",
        f"Research risk template: SL distance {sl * signal.atr:.2f}; TP distance {tp * signal.atr:.2f}; time stop {hold}h.",
    ]
    for k, v in signal.details.items():
        if k in {"z_now", "cointegration_p"} and signal.family == "pair_spread":
            continue
        lines.append(f"{k}: {v:.5g}" if isinstance(v, float) else f"{k}: {v}")
    subset = model.get("evidence", {}).get("subsets", {}).get(signal.label, {})
    if subset.get("trades"):
        lines.append(
            f"Held-out {signal.label}: {subset['wins']}/{subset['trades']} net winners; "
            f"conservative historical lower bound {subset['evidence_lower_bound']:.1%}."
        )
    lines += [
        "Historical subset statistics are NOT the probability of this trade winning.",
        "SELL/SHORT is a research direction; Coinbase spot borrow/short execution is NOT modeled.",
        "Indicative alert only. No broker connection, no order, no automatic stop-loss.",
    ]
    return "\n".join(lines)


def scan(config, store, output: Path, mode="strict", dry_run=False, manual=False, now=None):
    now = utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    model = store.get("model.json")
    runtime = store.get("runtime.json", {})
    ok, reasons = eligibility(model, config, now)
    output.mkdir(parents=True, exist_ok=True)
    messages = []

    if mode == "demo":
        messages = [
            "DEMO - SYNTHETIC MESSAGE - NOT A LIVE SIGNAL\n"
            "BTC QUANT BOT 2 v1.1.1 | 1H\n"
            "Connection test only. No real-market edge is implied.\n"
            "No order or position has been created."
        ]
    elif mode == "status":
        messages = [status_message(model, reasons, config)]
    else:
        paper = mode == "paper"
        if paper and not manual:
            raise ValueError("Paper mode requires a manual workflow dispatch")
        position_key = "paper_position" if paper else "strict_position"
        existing_position = runtime.get(position_key)

        if not model or not model.get("selected") or (not ok and not paper and not existing_position):
            if manual or (runtime.get("heartbeat_date") != str(now.date()) and now.hour == config["alerts"]["heartbeat_hour_utc"]):
                messages = [status_message(model, reasons, config)]
                runtime["heartbeat_date"] = str(now.date())
        else:
            if model.get("fingerprint") != fingerprint(config):
                raise DataError("Model fingerprint mismatch")
            selected = model["selected"]
            symbols = [config["data"]["bitcoin"], selected["peer"]]
            prices, diagnostics = live_history(config, symbols, now)
            write_json(output / "price_diagnostics.json", diagnostics)

            position = runtime.get(position_key)
            if position:
                if position.get("model_fingerprint") != model["fingerprint"]:
                    raise DataError("Earlier model has an unresolved alert-position; inspect state deliberately")
                updated, message = monitor_position(position, prices, config, now)
                runtime[position_key] = updated
                if message:
                    messages.append(message)

            market_entry_block = any(d.get("spread_entry_block") for d in diagnostics.values())
            if market_entry_block and manual:
                messages.append(
                    "BTC BOT 2: NEW ENTRY BLOCKED - live Coinbase bid/ask spread exceeds the configured limit. "
                    "Existing simulated alert-position monitoring continues."
                )

            if not runtime.get(position_key) and (ok or paper) and not market_entry_block:
                closed = prices[symbols[0]].index[-1] + HOUR
                if now - closed > pd.Timedelta(minutes=config["execution"]["max_alert_delay_minutes"]):
                    if manual:
                        messages.append(
                            "BTC BOT 2: LATE RUN - entry withheld. New alerts are issued only shortly after a completed hourly candle."
                        )
                else:
                    cand = Candidate(selected["family"], selected["peer"])
                    events = generate_signals(prices[symbols[0]], prices[symbols[1]], cand, config)
                    current = [s for s in events if s.time + HOUR == closed]
                    sent_key = f"{mode}:{selected['id']}:{closed}"
                    if current and runtime.get("last_sent_key") != sent_key:
                        event = current[-1]
                        messages.append(entry_message(event, model, config, mode))
                        position = make_position(event, config, mode)
                        position["model_fingerprint"] = model["fingerprint"]
                        runtime[position_key] = position
                        runtime["last_sent_key"] = sent_key
                        write_json(output / "signal.json", event.to_dict())
                    elif manual:
                        messages.append(
                            f"BTC QUANT BOT 2 v1.1.1 | 1H\nNo NEW signal on latest completed bar ({closed}).\n"
                            f"Selected model: {selected['id']}\nNo forced BUY/SELL. No order placed."
                        )

            if not ok and not paper and manual and not messages:
                messages = [status_message(model, reasons, config)]
            if not messages and not manual and now.hour == config["alerts"]["heartbeat_hour_utc"] and runtime.get("heartbeat_date") != str(now.date()):
                messages = [
                    "BTC QUANT BOT 2 v1.1.1 - DAILY HEARTBEAT\nScanner completed. No new entry message this hour.\n"
                    "State here is a simulated alert state, not a broker account."
                ]
                runtime["heartbeat_date"] = str(now.date())

    text = "\n\n".join(messages) or "No message required on this run."
    (output / "telegram_preview.txt").write_text(text, encoding="utf-8")
    write_json(output / "scan_summary.json", {
        "mode": mode, "now": now, "strict_eligible": ok, "strict_reasons": reasons,
        "messages": len(messages), "dry_run": dry_run,
    })
    if not dry_run:
        for msg in messages:
            telegram.send(msg)
        if mode not in ("demo", "status"):
            store.put("runtime.json", runtime)
    print(text)
    return messages


def check_data(config, output):
    """Verify the NEW provider from the actual GitHub runner before research."""
    output.mkdir(parents=True, exist_ok=True)
    cfg = config["data"]
    client = PublicClient(cfg["timeout_seconds"], cfg["retries"], cfg.get("pause_seconds", 0.18))
    now = pd.Timestamp.now(tz="UTC").floor("h")
    checks = {}

    for product in [cfg["bitcoin"], *cfg["peers"]]:
        try:
            bars = fetch_candles(client, product, now - pd.Timedelta(hours=6), now)
            book = fetch_book(client, product)
            checks[product] = {
                "status": "OK", "bars": len(bars), "last_bar_start": str(bars.index[-1]),
                "spread_bps": book["spread_bps"], "provider": "coinbase_exchange_public_spot",
            }
        except DataError as exc:
            checks[product] = {"status": "FAILED", "reason": str(exc)}

    write_json(output / "provider_check.json", checks)
    for name, item in checks.items():
        print(name, item)
    if any(c["status"] != "OK" for c in checks.values()):
        raise DataError(
            "One or more Coinbase spot provider checks failed; inspect provider_check.json. "
            "No proxy, bypass, or silent venue substitution was attempted."
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description="BTC Quant Bot 2 v1.1.1 - Coinbase spot 1h research alerts; no trading API")
    parser.add_argument("command", choices=["setup", "check-data", "research", "scan"])
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="output")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--mode", choices=["strict", "paper", "demo", "status"], default="strict")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--manual", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    store = Store(Path(args.state_dir), cfg["alerts"]["state_branch"])

    try:
        if args.command == "setup":
            telegram.setup_bot()
        elif args.command == "check-data":
            check_data(cfg, output)
        elif args.command == "research":
            if args.download:
                download_history(cfg, Path(args.data_dir), output)
            prices, funds = load_history(cfg, Path(args.data_dir))
            model = research(cfg, prices, funds, output, source=REAL_SOURCE)
            store.put("model.json", model)
            store.put("last_research.json", {
                "status": model["status"], "date": model["created_at"], "selected": model["selected"],
            })
            if args.notify:
                ok, reasons = eligibility(model, cfg, pd.Timestamp.now(tz="UTC"))
                telegram.send("RESEARCH BACKTEST COMPLETED\n" + status_message(model, reasons, cfg))
        else:
            scan(cfg, store, output, args.mode, args.dry_run, args.manual)
    except Exception as exc:
        error = {
            "status": "FAILED", "type": type(exc).__name__, "reason": str(exc)[:500],
            "delivery_status": "Unconfirmed: check Telegram/state; failure can occur after message acceptance",
        }
        write_json(output / "error.json", error)
        print(f"FAILED: {error['type']}: {error['reason']}")
        if args.command == "scan" and not args.dry_run and os.environ.get("TELEGRAM_BOT2_TOKEN") and os.environ.get("TELEGRAM_BOT2_CHAT_ID"):
            try:
                telegram.send(
                    "BTC QUANT BOT 2 v1.1.1 - SCANNER FAILED\n"
                    "The scan did not complete; inspect the GitHub Actions artifact.\n"
                    "No broker account can be inspected or changed by this bot."
                )
            except telegram.TelegramError:
                print("Telegram failure notification could not be confirmed.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
