"""Event-driven, non-overlapping trades. Synthetic testing is NOT market evidence."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .common import HOUR, utc, DataError
from .signals import Candidate, Signal, generate_signals


def directional_rules(family: str, config: dict) -> tuple[float, float, int]:
    s = config["signals"]
    if family == "divergence": return 1.5, 2.0, s["directional_max_holding_hours"]
    if family == "lead_lag": return 1.5, 2.0, s["lead_horizon_hours"]
    return 2.0, 3.0, s["directional_max_holding_hours"]


def funding_cashflow(funding: pd.DataFrame, prices: pd.DataFrame, entry_time, exit_time, quantity: float) -> float:
    """Signed PnL. Positive rate costs longs and pays shorts. Price is an OPEN proxy for mark price."""
    events = funding.loc[(funding.index > entry_time) & (funding.index <= exit_time)]
    if events.empty: return 0.0
    # Event timestamps can be a few milliseconds after the hour.
    loc = prices.index.get_indexer(events.index.floor("h"))
    if (loc < 0).any(): raise DataError("Cannot value funding event without its hourly candle")
    return float(np.sum(-quantity * prices.open.iloc[loc].to_numpy() * events.rate.to_numpy()))


def directional_exit(bar, direction: int, stop: float, target: float) -> tuple[float | None, str | None]:
    """Broker-native barrier assumption. An unresolved same-bar tie always loses."""
    o, h, l = float(bar.open), float(bar.high), float(bar.low)
    if direction == 1:
        if o <= stop: return o, "STOP_GAP"
        if l <= stop: return stop, "STOP_OR_AMBIGUOUS_STOP_FIRST"
        if h >= target: return target, "TAKE_PROFIT"
    else:
        if o >= stop: return o, "STOP_GAP"
        if h >= stop: return stop, "STOP_OR_AMBIGUOUS_STOP_FIRST"
        if l <= target: return target, "TAKE_PROFIT"
    return None, None


def run_backtest(btc: pd.DataFrame, peer: pd.DataFrame | None, btc_funding: pd.DataFrame,
                 peer_funding: pd.DataFrame | None, candidate: Candidate, config: dict,
                 start, end, signals: list[Signal] | None = None) -> tuple[pd.DataFrame, pd.Series]:
    start, end = utc(start), utc(end)
    if not btc.index.is_monotonic_increasing or btc.index.has_duplicates: raise DataError("Bad candle ordering")
    if peer is not None and not peer.index.equals(btc.index): raise DataError("Pair clocks do not match")
    events = generate_signals(btc, peer, candidate, config) if signals is None else signals
    ex, sigcfg = config["execution"], config["signals"]
    unit_cost = (ex["fee_bps_per_side"] + ex["slippage_bps_per_side"]) / 10000
    index = btc.index
    equity = pd.Series(1.0, index=index[(index >= start) & (index < end)], name="equity")
    if equity.empty: return pd.DataFrame(), equity
    n = len(btc)
    # Last included bar. A trade needs enough time for its full time stop, not a forced winner-only exit.
    last_valid = int(index.searchsorted(end)) - 1
    previous_exit, wealth = -100000, 1.0
    rows = []
    for signal in sorted(events, key=lambda z: z.index):
        i = signal.index
        known_time = index[i] + HOUR
        if not start <= known_time < end: continue
        if i <= previous_exit + ex["cooldown_bars"]: continue
        e = i + ex["entry_delay_bars"]
        if e >= n or index[e] >= end: continue
        hold = sigcfg["pair_max_holding_hours"] if candidate.family == "pair_spread" else directional_rules(candidate.family, config)[2]
        # End embargo prevents censored trades leaking across validation/test boundaries.
        if e+hold+ex["close_exit_delay_bars"] > last_valid: continue
        d = signal.direction
        ep_b = float(btc.open.iloc[e])
        is_pair = candidate.family == "pair_spread"
        weight_b = 1/(1+signal.beta) if is_pair else 1.0
        weight_p = signal.beta/(1+signal.beta) if is_pair else 0.0
        ep_p = float(peer.open.iloc[e]) if is_pair else 0.0
        q_b = d*weight_b/ep_b
        q_p = -d*weight_p/ep_p if is_pair else 0.0
        entry_time = index[e]
        entry_cost = unit_cost  # gross notional is exactly 1.0, across both legs
        reason, exit_price_b, exit_price_p, j = "", 0.0, 0.0, e
        if is_pair:
            requested = None
            for j in range(e, e+hold+ex["close_exit_delay_bars"]+1):
                if requested is not None and j == requested:
                    exit_price_b, exit_price_p = float(btc.open.iloc[j]), float(peer.open.iloc[j])
                    break
                zb = (math.log(btc.close.iloc[j])-signal.alpha-signal.beta*math.log(peer.close.iloc[j])-signal.spread_mean)/signal.spread_std
                mark_profit = q_b*(float(btc.close.iloc[j])-ep_b)+q_p*(float(peer.close.iloc[j])-ep_p)
                if requested is None:
                    if abs(zb) <= sigcfg["pair_exit_z"] or d*zb >= 0:
                        reason, requested = "SPREAD_CONVERGED", j+ex["close_exit_delay_bars"]
                    elif abs(zb) >= sigcfg["pair_stop_z"] or mark_profit <= -sigcfg["pair_loss_limit"]:
                        reason, requested = "SPREAD_STOP_CLOSE_BASED", j+ex["close_exit_delay_bars"]
                    elif j-e+1 >= hold:
                        reason, requested = "TIME_STOP", j+ex["close_exit_delay_bars"]
            exit_time = index[j]
        else:
            sl_atr, tp_atr, hold = directional_rules(candidate.family, config)
            stop, target = ep_b-d*sl_atr*signal.atr, ep_b+d*tp_atr*signal.atr
            if stop <= 0 or target <= 0: continue
            hit = False
            for j in range(e, e+hold):
                fill, why = directional_exit(btc.iloc[j], d, stop, target)
                if fill is not None:
                    exit_price_b, reason, hit = float(fill), str(why), True
                    break
            if hit:
                # Exact intrabar fill ordering/time unknown. No future funding event at next hour.
                exit_time = index[j]+HOUR-pd.Timedelta(nanoseconds=1)
            else:
                j = e+hold
                exit_price_b, reason, exit_time = float(btc.open.iloc[j]), "TIME_STOP", index[j]
        gross = q_b*(exit_price_b-ep_b) + (q_p*(exit_price_p-ep_p) if is_pair else 0)
        exit_notional = abs(q_b)*exit_price_b + (abs(q_p)*exit_price_p if is_pair else 0)
        exit_cost = unit_cost*exit_notional
        funding_b = funding_cashflow(btc_funding, btc, entry_time, exit_time, q_b)
        funding_p = funding_cashflow(peer_funding, peer, entry_time, exit_time, q_p) if is_pair else 0.0
        funding_total = funding_b + funding_p
        costs = entry_cost+exit_cost
        net = gross+funding_total-costs
        stress_net = gross+funding_total-ex["stress_multiplier"]*costs
        # Mark-to-market close equity while in position. Fees/funding do not disappear until exit.
        for k in range(e, j+1):
            at = index[k]
            if at not in equity.index: continue
            if k == j:
                equity.loc[at] = wealth*(1+net)
            else:
                mtm = q_b*(float(btc.close.iloc[k])-ep_b)
                if is_pair: mtm += q_p*(float(peer.close.iloc[k])-ep_p)
                fp = funding_cashflow(btc_funding, btc, entry_time, at+HOUR-pd.Timedelta(nanoseconds=1), q_b)
                if is_pair: fp += funding_cashflow(peer_funding, peer, entry_time, at+HOUR-pd.Timedelta(nanoseconds=1), q_p)
                equity.loc[at] = wealth*(1+mtm+fp-entry_cost)
        wealth *= 1+net
        if wealth <= 0: raise DataError("Insolvent simulated portfolio; leverage/liquidation modeling not supplied")
        equity.loc[equity.index > index[j]] = wealth
        rows.append({"candidate": candidate.name, "family": candidate.family, "peer": candidate.peer,
            "signal_time": known_time, "entry_time": entry_time, "exit_time": exit_time,
            "direction": d, "bitcoin_action": signal.label, "two_legs": is_pair,
            "bitcoin_entry": ep_b, "bitcoin_exit": exit_price_b, "peer_entry": ep_p, "peer_exit": exit_price_p,
            "bitcoin_notional_weight": weight_b, "peer_notional_weight": weight_p,
            "beta_at_signal": signal.beta, "gross_return": gross, "funding_pnl": funding_total,
            "fees_and_slippage": costs, "net_return": net, "stress_net_return": stress_net,
            "win": net > 0, "exit_reason": reason, "holding_hours": float((exit_time-entry_time)/HOUR),
            "starting_equity": wealth/(1+net), "ending_equity": wealth})
        previous_exit = j
    return pd.DataFrame(rows), equity
