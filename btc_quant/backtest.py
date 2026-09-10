"""Event-driven BTC-only backtest using peer assets as signal context.

In v1.1 all candidates ultimately express a BTC BUY/LONG or SELL/SHORT research
signal. A pair relationship may create the signal, but the backtest does not
fabricate a companion short leg or borrow/funding cost on a spot venue.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import DataError, HOUR, utc
from .signals import Candidate, Signal, generate_signals


def directional_rules(family: str, config: dict) -> tuple[float, float, int]:
    s = config["signals"]
    if family == "divergence":
        return 1.5, 2.0, s["directional_max_holding_hours"]
    if family == "lead_lag":
        return 1.5, 2.0, s["lead_horizon_hours"]
    if family == "pair_spread":
        return 1.5, 2.0, s["pair_max_holding_hours"]
    return 2.0, 3.0, s["directional_max_holding_hours"]


def funding_cashflow(funding: pd.DataFrame | None, prices: pd.DataFrame, entry_time, exit_time, quantity: float) -> float:
    """Compatibility helper. Spot v1.1 has no funding, so empty/None means exactly zero."""
    if funding is None or funding.empty:
        return 0.0
    events = funding.loc[(funding.index > entry_time) & (funding.index <= exit_time)]
    if events.empty:
        return 0.0
    loc = prices.index.get_indexer(events.index.floor("h"))
    if (loc < 0).any():
        raise DataError("Cannot value funding event without its hourly candle")
    return float(np.sum(-quantity * prices.open.iloc[loc].to_numpy() * events.rate.to_numpy()))


def directional_exit(bar, direction: int, stop: float, target: float) -> tuple[float | None, str | None]:
    """Conservative intrabar barrier assumption: if both are possible, stop wins."""
    o, h, l = float(bar.open), float(bar.high), float(bar.low)
    if direction == 1:
        if o <= stop:
            return o, "STOP_GAP"
        if l <= stop:
            return stop, "STOP_OR_AMBIGUOUS_STOP_FIRST"
        if h >= target:
            return target, "TAKE_PROFIT"
    else:
        if o >= stop:
            return o, "STOP_GAP"
        if h >= stop:
            return stop, "STOP_OR_AMBIGUOUS_STOP_FIRST"
        if l <= target:
            return target, "TAKE_PROFIT"
    return None, None


def run_backtest(
    btc: pd.DataFrame,
    peer: pd.DataFrame | None,
    btc_funding: pd.DataFrame | None,
    peer_funding: pd.DataFrame | None,
    candidate: Candidate,
    config: dict,
    start,
    end,
    signals: list[Signal] | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    start, end = utc(start), utc(end)
    if not btc.index.is_monotonic_increasing or btc.index.has_duplicates:
        raise DataError("Bad candle ordering")
    if peer is not None and not peer.index.equals(btc.index):
        raise DataError("Pair clocks do not match")
    events = generate_signals(btc, peer, candidate, config) if signals is None else signals
    ex = config["execution"]
    unit_cost = (ex["fee_bps_per_side"] + ex["slippage_bps_per_side"]) / 10000.0
    index = btc.index
    equity = pd.Series(1.0, index=index[(index >= start) & (index < end)], name="equity")
    if equity.empty:
        return pd.DataFrame(), equity

    n = len(btc)
    last_valid = int(index.searchsorted(end)) - 1
    previous_exit = -100000
    wealth = 1.0
    rows = []

    for signal in sorted(events, key=lambda z: z.index):
        i = signal.index
        known_time = index[i] + HOUR
        if not start <= known_time < end:
            continue
        if i <= previous_exit + ex["cooldown_bars"]:
            continue
        e = i + ex["entry_delay_bars"]
        if e >= n or index[e] >= end:
            continue
        sl_atr, tp_atr, hold = directional_rules(candidate.family, config)
        if e + hold > last_valid:
            continue

        d = signal.direction
        ep = float(btc.open.iloc[e])
        q = d / ep
        stop = ep - d * sl_atr * signal.atr
        target = ep + d * tp_atr * signal.atr
        if stop <= 0 or target <= 0:
            continue

        reason = ""
        exit_price = 0.0
        j = e
        hit = False
        for j in range(e, e + hold):
            fill, why = directional_exit(btc.iloc[j], d, stop, target)
            if fill is not None:
                exit_price, reason, hit = float(fill), str(why), True
                break
        if hit:
            exit_time = index[j] + HOUR - pd.Timedelta(nanoseconds=1)
        else:
            j = e + hold
            exit_price, reason, exit_time = float(btc.open.iloc[j]), "TIME_STOP", index[j]

        gross = q * (exit_price - ep)
        entry_cost = unit_cost
        exit_notional = abs(q) * exit_price
        exit_cost = unit_cost * exit_notional
        costs = entry_cost + exit_cost
        net = gross - costs
        stress_net = gross - ex["stress_multiplier"] * costs

        for k in range(e, j + 1):
            at = index[k]
            if at not in equity.index:
                continue
            if k == j:
                equity.loc[at] = wealth * (1 + net)
            else:
                mtm = q * (float(btc.close.iloc[k]) - ep)
                equity.loc[at] = wealth * (1 + mtm - entry_cost)
        wealth *= 1 + net
        if wealth <= 0:
            raise DataError("Insolvent simulated portfolio; leverage/liquidation modeling not supplied")
        equity.loc[equity.index > index[j]] = wealth

        rows.append({
            "candidate": candidate.name,
            "family": candidate.family,
            "peer": candidate.peer,
            "signal_time": known_time,
            "entry_time": index[e],
            "exit_time": exit_time,
            "direction": d,
            "bitcoin_action": signal.label,
            "two_legs": False,
            "bitcoin_entry": ep,
            "bitcoin_exit": exit_price,
            "beta_at_signal": signal.beta,
            "gross_return": gross,
            "funding_pnl": 0.0,
            "fees_and_slippage": costs,
            "net_return": net,
            "stress_net_return": stress_net,
            "win": net > 0,
            "exit_reason": reason,
            "holding_hours": float((exit_time - index[e]) / HOUR),
            "starting_equity": wealth / (1 + net),
            "ending_equity": wealth,
        })
        previous_exit = j

    return pd.DataFrame(rows), equity
