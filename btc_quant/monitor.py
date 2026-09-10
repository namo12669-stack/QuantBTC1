"""Simulated alert-position tracking; never assumes access to an exchange account."""
from __future__ import annotations

from .common import utc, HOUR
from .backtest import directional_rules, directional_exit


def make_position(signal, config, mode):
    return {
        "mode": mode,
        "signal": signal.to_dict(),
        "entry_time": str(signal.time + HOUR * config["execution"]["entry_delay_bars"]),
        "last_checked": None,
        "exit_due": None,
        "status": "PENDING_ENTRY",
        "actual_broker_position": "UNKNOWN",
    }


def monitor_position(position: dict, prices: dict, config: dict, now) -> tuple[dict | None, str | None]:
    now = utc(now)
    btc = prices[config["data"]["bitcoin"]]
    sig = position["signal"]
    entry_time = utc(position["entry_time"])
    d = sig["direction"]
    prefix = "PAPER OBSERVATION" if position["mode"] == "paper" else "MODEL OBSERVATION - NOT A BROKER FILL"

    if position.get("exit_due"):
        release = utc(position.get("cooldown_until", str(utc(position["exit_due"]) + HOUR * (config["execution"]["cooldown_bars"] + 2))))
        if now >= release:
            return None, None
        return position, None
    if entry_time not in btc.index:
        return position, None
    if "bitcoin_entry" not in position:
        position["bitcoin_entry"] = float(btc.loc[entry_time, "open"])
        position["status"] = "PAPER_POSITION_OPEN"

    ep = position["bitcoin_entry"]
    bars = btc.loc[btc.index >= entry_time]
    if position.get("last_checked"):
        bars = bars.loc[bars.index > utc(position["last_checked"])]
    sl, tp, hold = directional_rules(sig["family"], config)
    stop, target = ep - d * sl * sig["atr"], ep + d * tp * sig["atr"]

    for at, row in bars.iterrows():
        count = int((at - entry_time) / HOUR) + 1
        fill, reason = directional_exit(row, d, stop, target)
        due = None
        if fill is not None:
            due = at + HOUR
            position["paper_exit_price"] = float(fill)
        elif count >= hold:
            reason, due = "TIME_STOP", at + HOUR
        position["last_checked"] = str(at)
        if reason:
            position["status"] = "EXIT_OBSERVED_OR_PLANNED"
            position["exit_due"] = str(due)
            position["exit_bar_open"] = str(at)
            position["cooldown_until"] = str(at + HOUR * (config["execution"]["cooldown_bars"] + 2))
            late = now > due
            return position, (
                f"{prefix}\nCLOSE BTC POSITION: {reason}\nModel exit time: {due}\n"
                f"{'TIME HAS PASSED; review any real position now.' if late else 'Planned exit time has not yet arrived.'}\n"
                "Hourly alerts are NOT stop-loss orders. No position or order was changed by this bot."
            )
    return position, None
