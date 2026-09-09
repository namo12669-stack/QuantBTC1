from __future__ import annotations
import argparse
import os
from pathlib import Path
import pandas as pd
from .common import ROOT, HOUR, utc, write_json, load_config, fingerprint, DataError
from .data import download_history, load_history, live_history, PublicClient, API, ARCHIVE
from .signals import Candidate, generate_signals
from .research import research
from .store import Store
from . import telegram
from .backtest import directional_rules
from .monitor import make_position, monitor_position


def eligibility(model: dict | None, config: dict, now) -> tuple[bool, list[str]]:
    if not model: return False, ["NO_BACKTEST_MODEL: run Research Backtest first"]
    reasons = []
    if model.get("source") != "real_exchange_archive": reasons.append("REAL_DATA_EVIDENCE_REQUIRED")
    if model.get("fingerprint") != fingerprint(config): reasons.append("CODE_OR_CONFIG_CHANGED: rerun research")
    if not model.get("approved") or not model.get("evidence", {}).get("approved"):
        reasons.append("90_PERCENT_HISTORICAL_EVIDENCE_NOT_PASSED")
    end = model.get("test_end_exclusive")
    if not end or utc(now)-utc(end) > pd.Timedelta(days=config["proof_gate"]["max_evidence_age_days"]):
        reasons.append("BACKTEST_EVIDENCE_STALE")
    if end and utc(end) > utc(now): reasons.append("FUTURE_TEST_END_INVALID")
    return not reasons, reasons


def status_message(model, reasons):
    selected = model.get("selected") if model else None
    text = ["BTC QUANT BOT 2 | 1H", "STATUS: NO APPROVED ENTRY" if reasons else "STATUS: HISTORICAL EVIDENCE GATE PASSED",
            f"Candidate: {selected['id'] if selected else 'not selected - research not completed'}"]
    if reasons: text.extend(reasons)
    if model and model.get("evidence"):
        ev = model["evidence"]["subsets"].get("overall", {})
        if ev.get("trades"):
            text.append(f"Holdout: {ev['wins']}/{ev['trades']} net winners; conservative historical lower bound {ev['evidence_lower_bound']:.1%}")
    text.extend(["No per-signal win probability is estimated. No guarantee of 90% or profit.",
                 "No order placed. Paper mode is research-only and must be requested manually."])
    return "\n".join(text)


def entry_message(signal, model, config, mode):
    entry = signal.time + HOUR*config["execution"]["entry_delay_bars"]
    pair = signal.family == "pair_spread"
    lines = ["BTC QUANT BOT 2 | CLOSED 1H", "PAPER ONLY - NO VERIFIED 90% EDGE" if mode == "paper" else "HISTORICAL EVIDENCE GATE PASSED - NOT A GUARANTEE",
        f"BTC: {signal.label} ({'LONG' if signal.direction > 0 else 'SHORT'})", f"Signal: {signal.family}", f"Confirmed at: {signal.time+HOUR}", f"Planned entry: {entry} (next full hourly open)"]
    if pair:
        peer_action = "SELL / SHORT" if signal.direction > 0 else "BUY / LONG"
        lines += [f"{signal.peer}: {peer_action} - REQUIRED HEDGE LEG",
                  f"Gross notional split: BTC {1/(1+signal.beta):.1%}, peer {signal.beta/(1+signal.beta):.1%}",
                  f"Spread z {signal.details['z_now']:.2f}; beta {signal.beta:.3f}; formation coint p {signal.details['cointegration_p']:.4f}",
                  "Taking BTC alone is NOT the backtested pair strategy.",
                  f"Exit: |z| <= {config['signals']['pair_exit_z']}, close-based risk stop |z| >= {config['signals']['pair_stop_z']} or gross pair loss >= {config['signals']['pair_loss_limit']:.1%}; time cap {config['signals']['pair_max_holding_hours']}h.",
                  "Pair exits wait for hourly close, then next planned hourly open. Loss limits are NOT guaranteed."]
    else:
        sl, tp, hold = directional_rules(signal.family, config)
        lines += [f"Context peer: {signal.peer} (NO peer order)",
                  f"ATR at signal: {signal.atr:.2f} USDT; SL distance {sl*signal.atr:.2f}; TP distance {tp*signal.atr:.2f} from actual BTC fill.",
                  f"Time stop: {hold} hours after entry. Native exchange TP/SL is required; this bot cannot place it."]
        for k, v in signal.details.items():
            lines.append(f"{k}: {v:.5g}" if isinstance(v, float) else f"{k}: {v}")
    subset = model.get("evidence", {}).get("subsets", {}).get(signal.label, {})
    if subset.get("trades"):
        lines.append(f"Held-out {signal.label}: {subset['wins']}/{subset['trades']} net winners; historical lower bound {subset['evidence_lower_bound']:.1%}.")
    lines += ["Historical subset statistics are NOT the probability of this trade winning.",
              "Indicative plan, not a live order. SELL here means opening a SHORT, not selling existing spot BTC.",
              "No leverage recommendation. Funding, gaps, outages and manual execution can change results."]
    return "\n".join(lines)


def scan(config, store, output: Path, mode="strict", dry_run=False, manual=False, now=None):
    now = utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    model = store.get("model.json")
    runtime = store.get("runtime.json", {})
    ok, reasons = eligibility(model, config, now)
    output.mkdir(parents=True, exist_ok=True)
    messages = []
    if mode == "demo":
        messages = ["DEMO - SYNTHETIC MESSAGE - NOT A LIVE SIGNAL\nBTC QUANT BOT 2 | 1H\nConnection test only. No real market backtest is bundled.\nBUY/SELL notifications remain blocked until evidence is available.\nNo order or position has been created."]
    elif mode == "status":
        messages = [status_message(model, reasons)]
    else:
        paper = mode == "paper"
        if paper and not manual: raise ValueError("Paper mode requires a manual workflow dispatch")
        position_key = "paper_position" if paper else "strict_position"
        existing_position = runtime.get(position_key)
        # A failed/stale entry gate must NOT suppress exit observations for an existing alert-position.
        if not model or not model.get("selected") or (not ok and not paper and not existing_position):
            if manual or runtime.get("heartbeat_date") != str(now.date()) and now.hour == config["alerts"]["heartbeat_hour_utc"]:
                messages = [status_message(model, reasons)]
                runtime["heartbeat_date"] = str(now.date())
        else:
            # Even paper mode cannot reuse a different implementation's model selection.
            if model.get("fingerprint") != fingerprint(config): raise DataError("Model fingerprint mismatch")
            selected = model["selected"]
            symbols = [config["data"]["bitcoin"], selected["peer"]]
            prices, diagnostics = live_history(config, symbols, now)
            write_json(output / "price_diagnostics.json", diagnostics)
            key = "paper_position" if paper else "strict_position"
            position = runtime.get(key)
            if position:
                if position.get("model_fingerprint") != model["fingerprint"]:
                    raise DataError("An earlier model has an unresolved alert-position; inspect actual positions and clear state deliberately")
                updated, message = monitor_position(position, prices, config, now)
                runtime[key] = updated
                if message: messages.append(message)
            market_entry_block = any(d.get("funding_entry_block") or d.get("spread_entry_block") for d in diagnostics.values())
            if market_entry_block and manual:
                messages.append("BTC BOT 2: NEW ENTRY BLOCKED - live spread or recent funding exceeds the configured limit. Existing alert-position monitoring continues.")
            if not runtime.get(key) and (ok or paper) and not market_entry_block:
                closed = prices[symbols[0]].index[-1] + HOUR
                if now-closed > pd.Timedelta(minutes=config["execution"]["max_alert_delay_minutes"]):
                    if manual: messages.append("BTC BOT 2: LATE RUN - entry withheld. Alerts may only be issued within 25 minutes of the completed hourly candle.")
                else:
                    cand = Candidate(selected["family"], selected["peer"])
                    events = generate_signals(prices[symbols[0]], prices[symbols[1]], cand, config)
                    current = [s for s in events if s.time+HOUR == closed]
                    sent_key = f"{mode}:{selected['id']}:{closed}"
                    if current and runtime.get("last_sent_key") != sent_key:
                        event = current[-1]
                        messages.append(entry_message(event, model, config, mode))
                        position = make_position(event, config, mode)
                        position["model_fingerprint"] = model["fingerprint"]
                        runtime[key] = position
                        runtime["last_sent_key"] = sent_key
                        write_json(output / "signal.json", event.to_dict())
                    elif manual:
                        messages.append(f"BTC QUANT BOT 2 | 1H\nNo NEW signal on the latest completed bar ({closed}).\nSelected model: {selected['id']}\nNo forced BUY/SELL. No order placed.")
            if not ok and not paper and manual and not messages:
                messages = [status_message(model, reasons)]
            if not messages and not manual and now.hour == config["alerts"]["heartbeat_hour_utc"] and runtime.get("heartbeat_date") != str(now.date()):
                messages = ["BTC QUANT BOT 2 - DAILY HEARTBEAT\nScanner completed. No new entry message this hour.\nState and positions here are simulated alerts, not a broker account."]
                runtime["heartbeat_date"] = str(now.date())
    text = "\n\n".join(messages) or "No message required on this run."
    (output / "telegram_preview.txt").write_text(text, encoding="utf-8")
    write_json(output / "scan_summary.json", {"mode": mode, "now": now, "strict_eligible": ok, "strict_reasons": reasons, "messages": len(messages), "dry_run": dry_run})
    if not dry_run:
        for msg in messages: telegram.send(msg)
        if mode not in ("demo", "status"):
            # Best-effort dedup: a crash after Telegram accepts but before state write can repeat an alert.
            store.put("runtime.json", runtime)
    print(text)
    return messages


def check_data(config, output):
    output.mkdir(parents=True, exist_ok=True)
    client = PublicClient(config["data"]["timeout_seconds"], config["data"]["retries"])
    checks = {}
    for name, url, params in [
        ("hourly_api", f"{API}/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "1h", "limit": 3}),
        ("funding_api", f"{API}/fapi/v1/fundingRate", {"symbol": "BTCUSDT", "limit": 3}),
        ("archive_checksum", f"{ARCHIVE}/klines/BTCUSDT/1h/BTCUSDT-1h-2025-01.zip.CHECKSUM", None),
        ("funding_archive_checksum", f"{ARCHIVE}/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2025-01.zip.CHECKSUM", None)]:
        try:
            r = client.get(url, params)
            checks[name] = {"status": "OK", "bytes": len(r.content)}
        except DataError as exc:
            checks[name] = {"status": "FAILED", "reason": str(exc)}
    write_json(output / "provider_check.json", checks)
    for name, item in checks.items(): print(name, item)
    if any(c["status"] != "OK" for c in checks.values()):
        raise DataError("One or more provider checks failed; inspect provider_check.json. No exchange/domain substitution was attempted.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="BTC Quant Bot 2 - research-first hourly alerts, no trading API")
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
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    store = Store(Path(args.state_dir), cfg["alerts"]["state_branch"])
    try:
        if args.command == "setup": telegram.setup_bot()
        elif args.command == "check-data": check_data(cfg, output)
        elif args.command == "research":
            if args.download: download_history(cfg, Path(args.data_dir), output)
            prices, funds = load_history(cfg, Path(args.data_dir))
            model = research(cfg, prices, funds, output)
            store.put("model.json", model)
            store.put("last_research.json", {"status": model["status"], "date": model["created_at"], "selected": model["selected"]})
            if args.notify:
                ok, reasons = eligibility(model, cfg, pd.Timestamp.now(tz="UTC"))
                telegram.send("RESEARCH BACKTEST COMPLETED\n"+status_message(model, reasons))
        else:
            scan(cfg, store, output, args.mode, args.dry_run, args.manual)
    except Exception as exc:
        # Exception messages from network wrappers are intentionally sanitized.
        error = {"status": "FAILED", "type": type(exc).__name__, "reason": str(exc)[:500], "delivery_status": "Unconfirmed: check Telegram and state; a failure can occur after a message is accepted"}
        write_json(output / "error.json", error)
        print(f"FAILED: {error['type']}: {error['reason']}")
        if args.command == "scan" and not args.dry_run and os.environ.get("TELEGRAM_BOT2_TOKEN") and os.environ.get("TELEGRAM_BOT2_CHAT_ID"):
            try:
                telegram.send("BTC QUANT BOT 2 - SCANNER FAILED\n"
                              "The scan did not complete; inspect the GitHub Actions error artifact.\n"
                              "Message delivery/state updates may be incomplete. Existing positions may not have been checked.\n"
                              "Do not rely on this hourly bot to enforce a stop. No broker account can be inspected or changed by the bot.")
            except telegram.TelegramError:
                print("Telegram failure notification could not be confirmed.")
        raise SystemExit(1) from None

if __name__ == "__main__": main()
