"""Alert-position tracking is simulated. It cannot see the user's actual account."""
from __future__ import annotations
import math
import pandas as pd
from .common import utc, HOUR
from .backtest import directional_rules, directional_exit


def make_position(signal, config, mode):
    return {"mode": mode, "signal": signal.to_dict(), "entry_time": str(signal.time + HOUR*config["execution"]["entry_delay_bars"]),
            "last_checked": None, "exit_due": None, "status": "PENDING_ENTRY", "actual_broker_position": "UNKNOWN"}


def monitor_position(position: dict, prices: dict, config: dict, now) -> tuple[dict | None, str | None]:
    """Return persisted state and at most one message. Native stops are only OBSERVED after bar completion."""
    now = utc(now)
    btc = prices[config["data"]["bitcoin"]]
    sig = position["signal"]
    entry_time = utc(position["entry_time"])
    peer = prices.get(sig["peer"])
    d = sig["direction"]
    pair = sig["family"] == "pair_spread"
    prefix = "PAPER OBSERVATION" if position["mode"] == "paper" else "MODEL OBSERVATION - NOT A BROKER FILL"
    if position.get("exit_due"):
        release = utc(position.get("cooldown_until", str(utc(position["exit_due"]) + HOUR*(config["execution"]["cooldown_bars"]+2))))
        if now >= release:
            return None, None
        return position, None
    if entry_time not in btc.index:
        return position, None
    if "bitcoin_entry" not in position:
        position["bitcoin_entry"] = float(btc.loc[entry_time, "open"])
        position["peer_entry"] = float(peer.loc[entry_time, "open"]) if pair else None
        position["status"] = "PAPER_POSITION_OPEN"
    ep = position["bitcoin_entry"]
    bars = btc.loc[btc.index >= entry_time]
    if position.get("last_checked"):
        bars = bars.loc[bars.index > utc(position["last_checked"])]
    for at, row in bars.iterrows():
        count = int((at-entry_time)/HOUR)+1
        due, reason = None, None
        if pair:
            pp = float(peer.loc[at, "close"])
            beta = sig["beta"]
            z = (math.log(row.close)-sig["alpha"]-beta*math.log(pp)-sig["spread_mean"])/sig["spread_std"]
            mark = d/(1+beta)*(row.close/ep-1)-d*beta/(1+beta)*(pp/position["peer_entry"]-1)
            cfg = config["signals"]
            if abs(z) <= cfg["pair_exit_z"] or d*z >= 0: reason = "SPREAD_CONVERGENCE"
            elif abs(z) >= cfg["pair_stop_z"] or mark <= -cfg["pair_loss_limit"]: reason = "PAIR_RISK_STOP"
            elif count >= cfg["pair_max_holding_hours"]: reason = "PAIR_TIME_STOP"
            if reason: due = at + HOUR*config["execution"]["close_exit_delay_bars"]
        else:
            sl, tp, hold = directional_rules(sig["family"], config)
            stop, target = ep-d*sl*sig["atr"], ep+d*tp*sig["atr"]
            fill, reason = directional_exit(row, d, stop, target)
            if fill is not None:
                due = at+HOUR
                position["paper_exit_price"] = float(fill)
            elif count >= hold:
                reason, due = "TIME_STOP", at+HOUR
        position["last_checked"] = str(at)
        if reason:
            position["status"] = "EXIT_OBSERVED_OR_PLANNED"
            position["exit_due"] = str(due)
            exit_bar = due if pair or reason == "TIME_STOP" else at
            position["exit_bar_open"] = str(exit_bar)
            position["cooldown_until"] = str(exit_bar + HOUR*(config["execution"]["cooldown_bars"]+2))
            late = now > due
            action = "CLOSE BOTH LEGS" if pair else "CLOSE BTC POSITION"
            return position, (f"{prefix}\n{action}: {reason}\nModel exit time: {due}\n"
                              f"{'TIME HAS PASSED; review actual position now.' if late else 'Planned exit time has not yet arrived.'}\n"
                              "Hourly alerts are NOT stop-loss orders. No position or order was changed by this bot.")
    return position, None
