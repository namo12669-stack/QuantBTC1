"""Historical-frequency evidence, NOT a per-trade calibrated probability model."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from scipy.stats import norm
from .common import utc


def wilson_lower(wins: int, trials: int, alpha: float = 0.05) -> float:
    if trials <= 0: return 0.0
    z = float(norm.ppf(1-alpha))
    p = wins/trials
    return float((p + z*z/(2*trials) - z*math.sqrt(p*(1-p)/trials + z*z/(4*trials**2))) / (1+z*z/trials))


def metrics(trades: pd.DataFrame, equity: pd.Series, start, end) -> dict:
    start, end = utc(start), utc(end)
    if trades.empty:
        return {"trades": 0, "wins": 0, "win_rate": None, "mean_net_return": None,
                "profit_factor": None, "total_return": 0.0, "daily_net_sharpe": 0.0,
                "max_drawdown_close_mtm": 0.0, "positive_month_fraction": 0.0,
                "mean_stress_return": None, "months": int((end.year-start.year)*12+end.month-start.month)}
    r = trades.net_return.to_numpy(float)
    wins = int((r > 0).sum())
    gains, losses = float(r[r > 0].sum()), float(-r[r < 0].sum())
    pf = gains/losses if losses > 0 else (float("inf") if gains > 0 else 0.0)
    daily = equity.resample("1D").last().ffill()
    dr = daily.pct_change(fill_method=None).fillna(daily.iloc[0]-1)
    sd = float(dr.std(ddof=1))
    sharpe = float(dr.mean()/sd*math.sqrt(365)) if sd > 1e-12 else 0.0
    path = np.r_[1.0, equity.to_numpy(float)]
    dd = float(np.max(1-path/np.maximum.accumulate(path)))
    month_eq = equity.resample("ME").last()
    mr = month_eq.pct_change(fill_method=None)
    if len(mr): mr.iloc[0] = month_eq.iloc[0]-1
    return {"trades": len(r), "wins": wins, "win_rate": wins/len(r),
            "mean_net_return": float(r.mean()), "mean_win": float(r[r>0].mean()) if wins else 0.0,
            "mean_loss": float(r[r<=0].mean()) if wins < len(r) else 0.0,
            "profit_factor": pf, "profit_factor_note": "no losing trades; infinite ratio, serialized as null" if losses == 0 and gains > 0 else "finite", "total_return": float(equity.iloc[-1]-1),
            "daily_net_sharpe": sharpe, "max_drawdown_close_mtm": dd,
            "positive_month_fraction": float((mr > 0).mean()),
            "mean_stress_return": float(trades.stress_net_return.mean()), "months": len(month_eq)}


def block_bounds(trades: pd.DataFrame, alpha: float, repetitions: int, seed: int) -> dict:
    if trades.empty: return {"block_win_lower": 0.0, "block_mean_lower": -1.0, "active_weeks": 0}
    t = trades.copy()
    stamp = pd.to_datetime(t.entry_time, utc=True)
    # Calendar weeks anchored at Monday. Sample circular blocks of FOUR consecutive weeks.
    weeks = (stamp.dt.floor("D")-pd.to_timedelta(stamp.dt.dayofweek, unit="D"))
    t["week"] = weeks
    grouped = t.groupby("week").agg(n=("net_return", "size"), wins=("win", "sum"), profit=("net_return", "sum"))
    calendar = pd.date_range(grouped.index.min(), grouped.index.max(), freq="7D")
    arr = grouped.reindex(calendar, fill_value=0).to_numpy(float)
    rng = np.random.default_rng(seed)
    n = len(arr)
    length = min(4, n)
    starts = rng.integers(0, n, size=(repetitions, math.ceil(n/length)))
    idx = (starts[:,:,None]+np.arange(length)) % n
    idx = idx.reshape(repetitions, -1)[:,:n]
    totals = arr[idx].sum(axis=1)
    valid = totals[:,0] > 0
    if valid.sum() < repetitions//2:
        return {"block_win_lower": 0.0, "block_mean_lower": -1.0, "active_weeks": len(grouped)}
    return {"block_win_lower": float(np.quantile(totals[valid,1]/totals[valid,0], alpha)),
            "block_mean_lower": float(np.quantile(totals[valid,2]/totals[valid,0], alpha)),
            "active_weeks": len(grouped), "calendar_weeks": n, "bootstrap_block_weeks": length}


def validate_evidence(trades: pd.DataFrame, equity: pd.Series, config: dict, start, end, source: str) -> dict:
    gate = config["proof_gate"]
    alpha = gate["family_alpha"]/gate["confidence_checks"]
    result = {"approved": False, "source": source, "per_trade_probability": None,
              "target": "historical net win-rate lower bound > 90%; not a next-trade guarantee",
              "family_alpha": gate["family_alpha"], "individual_alpha": alpha,
              "confidence_method": "minimum of one-sided Wilson and 4-calendar-week circular-block bootstrap",
              "subsets": {}, "reasons": []}
    common = metrics(trades, equity, start, end)
    result["test_metrics"] = common
    if source != "real_exchange_archive": result["reasons"].append("REAL_DATA_NOT_VERIFIED")
    if common["months"] < gate["minimum_test_calendar_months"]: result["reasons"].append("TOO_FEW_TEST_MONTHS")
    if common["max_drawdown_close_mtm"] > gate["maximum_drawdown"]: result["reasons"].append("DRAWDOWN_TOO_HIGH")
    if common["positive_month_fraction"] < gate["minimum_positive_month_fraction"]: result["reasons"].append("UNSTABLE_MONTHLY_RETURNS")
    if common["mean_stress_return"] is None or common["mean_stress_return"] <= 0: result["reasons"].append("COST_STRESS_NOT_PROFITABLE")
    for label, direction in (("overall", None), ("BUY", 1), ("SELL", -1)):
        sub = trades if direction is None or trades.empty else trades.loc[trades.direction == direction]
        trials = len(sub)
        wins = int(sub.win.sum()) if trials else 0
        wl = wilson_lower(wins, trials, alpha)
        bb = block_bounds(sub, alpha, gate["bootstrap_repetitions"], gate["seed"] + (direction or 0))
        lower = min(wl, bb["block_win_lower"])
        minimum = gate["minimum_test_trades"] if direction is None else gate["minimum_direction_trades"]
        min_weeks = gate["minimum_active_weeks"] if direction is None else gate["minimum_direction_active_weeks"]
        reason = []
        if trials < minimum: reason.append("INSUFFICIENT_TRADES")
        if bb["active_weeks"] < min_weeks: reason.append("INSUFFICIENT_ACTIVE_WEEKS")
        if lower <= gate["minimum_win_rate_lower_bound"]: reason.append("LOWER_BOUND_NOT_ABOVE_90_PERCENT")
        if bb["block_mean_lower"] <= 0: reason.append("EXPECTED_NET_RETURN_NOT_POSITIVE_AT_BOUND")
        if trials:
            rr = sub.net_return.to_numpy()
            pf = rr[rr > 0].sum()/(-rr[rr < 0].sum()) if np.any(rr < 0) else float("inf")
            if pf < gate["minimum_profit_factor"]: reason.append("LOW_PROFIT_FACTOR")
            if sub.stress_net_return.mean() <= 0: reason.append("SUBSET_COST_STRESS_FAILED")
        result["subsets"][label] = {"trades": trials, "wins": wins, "historical_win_rate": wins/trials if trials else None,
            "wilson_lower": wl, **bb, "evidence_lower_bound": lower, "passed": not reason, "reasons": reason}
        result["reasons"].extend(f"{label}:{r}" for r in reason)
    result["approved"] = not result["reasons"]
    return result
