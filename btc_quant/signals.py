"""Causal hourly hypotheses. These functions never estimate a win probability."""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from statsmodels.tsa.stattools import coint
from .common import HOUR, DataError

@dataclass(frozen=True)
class Candidate:
    family: str
    peer: str | None
    reward_risk: float = 1.5

    @property
    def name(self) -> str:
        return f"{self.family}__{self.peer or 'BTC_ONLY'}__RR{self.reward_risk:g}"

    def to_dict(self):
        return {"family": self.family, "peer": self.peer, "reward_risk": self.reward_risk, "id": self.name}

@dataclass
class Signal:
    index: int
    time: pd.Timestamp
    family: str
    peer: str | None
    direction: int
    atr: float
    details: dict = field(default_factory=dict)
    # Beta is a LOG-price elasticity. It sizes dollar notionals, not coin units.
    beta: float = 0.0
    alpha: float = 0.0
    spread_mean: float = 0.0
    spread_std: float = 0.0

    @property
    def label(self) -> str:
        return "BUY" if self.direction == 1 else "SELL"

    def to_dict(self):
        return {"signal_time": str(self.time + HOUR), "signal_bar_open": str(self.time), "family": self.family,
                "peer": self.peer, "direction": self.direction, "bitcoin_action": self.label,
                "atr": self.atr, "beta": self.beta, "alpha": self.alpha,
                "spread_mean": self.spread_mean, "spread_std": self.spread_std, "details": self.details}


def rma(series: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing with an SMA seed, resetting at every nonfinite value."""
    values=series.to_numpy(float);out=np.full(len(values),np.nan);seed=[];last=np.nan
    for i,x in enumerate(values):
        if not np.isfinite(x):seed=[];last=np.nan;continue
        if not np.isfinite(last):
            seed.append(x)
            if len(seed)==n:last=float(np.mean(seed));out[i]=last
        else:last=(last*(n-1)+x)/n;out[i]=last
    return pd.Series(out,index=series.index)


def indicator_frame(price: pd.DataFrame) -> pd.DataFrame:
    f=price.copy();change=f.close.diff()
    up=rma(change.clip(lower=0),14);down=rma(-change.clip(upper=0),14)
    f['rsi']=100-100/(1+up/down.replace(0,np.nan))
    f.loc[(down==0)&(up>0),'rsi']=100
    f.loc[(down==0)&(up==0),'rsi']=50
    tr=pd.concat([f.high-f.low,(f.high-f.close.shift()).abs(),(f.low-f.close.shift()).abs()],axis=1).max(axis=1)
    f['atr']=rma(tr,14)
    f['ema20']=f.close.ewm(span=20,adjust=False,min_periods=20).mean()
    f['rvol']=f.volume/f.volume.shift(1).rolling(24).median().replace(0,np.nan)
    return f


def adx(price: pd.DataFrame, n: int) -> pd.Series:
    up=price.high.diff();down=-price.low.diff()
    plus=up.where((up>down)&(up>0),0.);minus=down.where((down>up)&(down>0),0.)
    tr=pd.concat([price.high-price.low,(price.high-price.close.shift()).abs(),(price.low-price.close.shift()).abs()],axis=1).max(axis=1)
    denom=rma(tr,n).replace(0,np.nan)
    p=100*rma(plus,n)/denom;m=100*rma(minus,n)/denom
    dx=100*(p-m).abs()/(p+m).replace(0,np.nan)
    dx=dx.where((p+m)!=0,0.)
    return rma(dx,n)


def confirmed_pivots(values: np.ndarray, left: int, right: int, kind: str) -> list[tuple[int,int]]:
    """Return (pivot index, FIRST observable index). No retroactive signals."""
    result = []
    for pivot in range(left, len(values) - right):
        window = values[pivot-left:pivot+right+1]
        target = np.min(window) if kind == "low" else np.max(window)
        if np.isfinite(window).all() and values[pivot] == target and np.sum(window == target) == 1:
            result.append((pivot, pivot + right))
    return result


def _refits(index: pd.DatetimeIndex, window: int, every: int):
    hours = index.asi8 // HOUR.value
    return [i for i in range(window, len(index)) if hours[i] % every == 0]


def _ridge_fit(x, y, penalty=1.0):
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    z = np.column_stack([np.ones(len(x)), (x-mean)/scale])
    p = np.eye(z.shape[1]) * penalty
    p[0, 0] = 0.0
    coef = np.linalg.solve(z.T @ z + p, z.T @ y)
    return mean, scale, coef


def _ridge_predict(model, x):
    mean, scale, coef = model
    return np.column_stack([np.ones(len(x)), (x-mean)/scale]) @ coef


def _lead_features(btc: pd.DataFrame, peer: pd.DataFrame):
    rb, rp = np.log(btc.close).diff(), np.log(peer.close).diff()
    f = pd.DataFrame(index=btc.index)
    for lag in (1, 3, 6, 24): f[f"btc_r{lag}"] = np.log(btc.close / btc.close.shift(lag))
    f["btc_vol24"] = rb.rolling(24).std()
    f["btc_trend"] = btc.close / btc.close.ewm(span=48, min_periods=48).mean() - 1
    n_base = len(f.columns)
    for lag in (1, 3, 6, 24): f[f"peer_r{lag}"] = np.log(peer.close / peer.close.shift(lag))
    return f, n_base


def _generate_signals_contiguous(btc: pd.DataFrame, peer: pd.DataFrame | None, candidate: Candidate, config: dict) -> list[Signal]:
    s = config["signals"]
    f = indicator_frame(btc)
    if peer is not None and not btc.index.equals(peer.index): raise DataError("Unaligned pair candles")
    family = candidate.family
    if family in ("pair_spread", "lead_lag") and peer is None: raise ValueError("Relationship signal requires a peer")
    finite = np.isfinite(f.atr) & (f.atr > 0) & ((f.atr/f.close) < s["max_atr_fraction"])
    signals: list[Signal] = []
    if family == "trend_pullback":
        fast=f.close.ewm(span=s['ema_fast'],adjust=False,min_periods=s['ema_fast']).mean()
        slow=f.close.ewm(span=s['ema_slow'],adjust=False,min_periods=s['ema_slow']).mean()
        strength=adx(f,s['adx_period'])
        peer_ret=peer.close.pct_change(6,fill_method=None) if peer is not None else pd.Series(0.,index=f.index)
        peer_corr=np.log(btc.close).diff().rolling(168).corr(np.log(peer.close).diff()) if peer is not None else pd.Series(1.,index=f.index)
        warm=max(s['ema_slow']*4,s['adx_period']*3)
        for i in range(warm,len(f)):
            if not finite.iloc[i] or not np.isfinite(strength.iloc[i]) or strength.iloc[i]<s['adx_min']:continue
            d=1 if fast.iloc[i]>slow.iloc[i] else -1
            separation=abs(fast.iloc[i]-slow.iloc[i])/f.atr.iloc[i]
            reclaim=(f.low.iloc[i]<=fast.iloc[i] and f.close.iloc[i]>fast.iloc[i] and f.close.iloc[i]>f.close.iloc[i-1]) if d==1 else (f.high.iloc[i]>=fast.iloc[i] and f.close.iloc[i]<fast.iloc[i] and f.close.iloc[i]<f.close.iloc[i-1])
            if not reclaim or separation<s['ema_separation_atr']:continue
            if not np.isfinite(peer_ret.iloc[i]) or d*peer_ret.iloc[i]<0:continue
            if peer is not None and (not np.isfinite(peer_corr.iloc[i]) or peer_corr.iloc[i]<.30):continue
            signals.append(Signal(i,f.index[i],family,candidate.peer,d,float(f.atr.iloc[i]),
                {'ema_fast':float(fast.iloc[i]),'ema_slow':float(slow.iloc[i]),'adx':float(strength.iloc[i]),
                 'ema_separation_atr':float(separation),'peer_return_6h':float(peer_ret.iloc[i]),
                 'return_correlation_168h':float(peer_corr.iloc[i]),
                 'definition':'EMA27/125 + ADX90 >=14 + pullback reclaim; adapted hypothesis, not paper replication'}))
        return signals
    if family == "breakout":
        n = s["breakout_hours"]
        high = f.high.shift(1).rolling(n).max()
        low = f.low.shift(1).rolling(n).min()
        peer_ret = peer.close.pct_change(6) if peer is not None else pd.Series(0.0, index=f.index)
        for i in range(n+1, len(f)):
            if not finite.iloc[i] or not np.isfinite(f.rvol.iloc[i]) or f.rvol.iloc[i] < s["breakout_rvol"]: continue
            d = 1 if f.close.iloc[i] > high.iloc[i] else -1 if f.close.iloc[i] < low.iloc[i] else 0
            if d and d * peer_ret.iloc[i] >= 0 and d * (f.close.iloc[i] - f.ema20.iloc[i]) > 0:
                signals.append(Signal(i, f.index[i], family, candidate.peer, d, float(f.atr.iloc[i]),
                    {"prior_range_hours": n, "prior_high": float(high.iloc[i]), "prior_low": float(low.iloc[i]),
                     "close": float(f.close.iloc[i]), "rvol": float(f.rvol.iloc[i]), "peer_return_6h": float(peer_ret.iloc[i])}))
        return signals
    if family == "divergence":
        peer_ret = peer.close.pct_change(6) if peer is not None else pd.Series(0.0, index=f.index)
        for kind, d in (("low", 1), ("high", -1)):
            pivots = confirmed_pivots(f[kind].to_numpy(), s["pivot_left"], s["pivot_right"], kind)
            for (p0, _), (p1, observable) in zip(pivots, pivots[1:]):
                gap = p1-p0
                if not s["pivot_min_gap"] <= gap <= s["pivot_max_gap"]: continue
                if not finite.iloc[observable]: continue
                p_change = f[kind].iloc[p1] / f[kind].iloc[p0] - 1
                r_change = f.rsi.iloc[p1] - f.rsi.iloc[p0]
                if not np.isfinite(r_change): continue
                if d*p_change > -s["divergence_min_price_fraction"] or d*r_change < s["divergence_min_rsi_delta"]: continue
                if d*peer_ret.iloc[observable] < 0 or not np.isfinite(peer_ret.iloc[observable]): continue
                if d*(f.close.iloc[observable] - f.close.iloc[observable-1]) <= 0: continue
                signals.append(Signal(observable, f.index[observable], family, candidate.peer, d, float(f.atr.iloc[observable]),
                    {"pivot_1": str(f.index[p0]), "pivot_2": str(f.index[p1]), "price_1": float(f[kind].iloc[p0]),
                     "price_2": float(f[kind].iloc[p1]), "rsi_1": float(f.rsi.iloc[p0]), "rsi_2": float(f.rsi.iloc[p1]),
                     "confirmation_bars": s["pivot_right"], "peer_return_6h": float(peer_ret.iloc[observable])}))
        return sorted(signals, key=lambda x: x.index)
    if family == "pair_spread":
        x, y = np.log(peer.close.to_numpy()), np.log(btc.close.to_numpy())
        window, every = s["pair_formation_hours"], s["refit_hours"]
        anchors = _refits(f.index, window, every)
        for a in anchors:
            xx, yy = x[a-window:a], y[a-window:a]
            design = np.column_stack([np.ones(window), xx])
            alpha, beta = np.linalg.lstsq(design, yy, rcond=None)[0]
            if not 0.1 <= beta <= 5.0: continue
            spread = yy - alpha - beta*xx
            mu, sigma = float(spread.mean()), float(spread.std(ddof=1))
            if sigma < 1e-6: continue
            denom = np.var(spread[:-1])
            rho = np.cov(spread[:-1], spread[1:], ddof=0)[0,1] / denom if denom > 1e-12 else np.nan
            if not 0 < rho < 1: continue
            half_life = -math.log(2) / math.log(rho)
            corr = float(np.corrcoef(np.diff(xx), np.diff(yy))[0,1])
            if not s["pair_min_half_life"] <= half_life <= s["pair_max_half_life"] or corr < s["pair_min_return_correlation"]: continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try: pvalue = float(coint(yy, xx, trend="c", maxlag=1, autolag=None)[1])
                except (ValueError, np.linalg.LinAlgError): continue
            if not np.isfinite(pvalue) or pvalue >= s["pair_coint_p"]: continue
            end = min(a + every, len(f))
            # Previous and present spread use SAME coefficients, even on refit boundaries.
            for i in range(a, end):
                z0 = (y[i-1] - alpha - beta*x[i-1] - mu) / sigma
                z1 = (y[i] - alpha - beta*x[i] - mu) / sigma
                threshold = s["pair_entry_z"]
                crossed = abs(z0) >= threshold and 1.0 < abs(z1) < threshold and z0*z1 > 0
                if crossed and finite.iloc[i]:
                    direction = -1 if z1 > 0 else 1
                    signals.append(Signal(i, f.index[i], family, candidate.peer, direction, float(f.atr.iloc[i]),
                        {"z_previous": float(z0), "z_now": float(z1), "cointegration_p": pvalue,
                         "half_life_hours": half_life, "return_correlation": corr, "formation_end": str(f.index[a]-pd.Timedelta(nanoseconds=1)),
                         "formation_hours": window}, float(beta), float(alpha), mu, sigma))
        return signals
    if family == "lead_lag":
        features, n_base = _lead_features(btc, peer)
        xx = features.to_numpy()
        delay, horizon = config["execution"]["entry_delay_bars"], s["lead_horizon_hours"]
        target = np.log(btc.open.shift(-(delay+horizon)) / btc.open.shift(-delay)).to_numpy()
        window, inner, every = s["lead_formation_hours"], s["lead_inner_test_hours"], s["refit_hours"]
        maturity = delay+horizon
        for a in _refits(f.index, window, every):
            v_start, v_stop = a-inner, a-maturity
            t_start, t_stop = a-window, v_start-maturity
            train_ids = np.arange(t_start, t_stop)
            val_ids = np.arange(v_start, v_stop)
            train_ids = train_ids[np.isfinite(xx[train_ids]).all(axis=1) & np.isfinite(target[train_ids])]
            val_ids = val_ids[np.isfinite(xx[val_ids]).all(axis=1) & np.isfinite(target[val_ids])]
            if len(train_ids) < 1000 or len(val_ids) < 150: continue
            full_model = _ridge_fit(xx[train_ids], target[train_ids])
            base_model = _ridge_fit(xx[train_ids, :n_base], target[train_ids])
            pred = _ridge_predict(full_model, xx[val_ids])
            pred_base = _ridge_predict(base_model, xx[val_ids, :n_base])
            yv = target[val_ids]
            base_mse = float(np.mean((yv-pred_base)**2))
            full_mse = float(np.mean((yv-pred)**2))
            improvement = 1-full_mse/base_mse if base_mse > 1e-15 else -1
            if np.std(pred) < 1e-12: continue
            ic = float(spearmanr(pred, yv).statistic)
            if not np.isfinite(ic) or improvement < s["lead_min_mse_improvement"] or ic < s["lead_min_inner_ic"]: continue
            all_ids = np.arange(a-window, a-maturity)
            all_ids = all_ids[np.isfinite(xx[all_ids]).all(axis=1) & np.isfinite(target[all_ids])]
            # Every target used here matures BEFORE the refit observation.
            model = _ridge_fit(xx[all_ids], target[all_ids])
            cost = 2*(config["execution"]["fee_bps_per_side"]+config["execution"]["slippage_bps_per_side"])/10000
            threshold = max(s["lead_forecast_cost_multiple"]*cost, s["lead_forecast_sigma_multiple"]*math.sqrt(full_mse))
            end = min(a+every, len(f))
            for i in range(a, end):
                if not finite.iloc[i] or not np.isfinite(xx[i]).all(): continue
                forecast = float(_ridge_predict(model, xx[i:i+1])[0])
                if abs(forecast) >= threshold:
                    signals.append(Signal(i, f.index[i], family, candidate.peer, 1 if forecast > 0 else -1, float(f.atr.iloc[i]),
                        {"forecast_log_return": forecast, "minimum_forecast": threshold,
                         "inner_mse_improvement": improvement, "inner_rank_ic": ic,
                         "forecast_horizon_hours": horizon, "last_training_label_before": str(f.index[a]),
                         "probability": "NOT_ESTIMATED"}))
        return signals
    raise ValueError(f"Unknown signal family: {family}")

def generate_signals(btc: pd.DataFrame, peer: pd.DataFrame | None, candidate: Candidate, config: dict) -> list[Signal]:
    """Generate signals only inside contiguous complete-data segments.

    Missing candles remain missing. Indicators, regressions and pair statistics are
    restarted after every gap so a rolling window never silently bridges absent data.
    Signal.index is remapped to the original hourly grid for the backtester.
    """
    if len(btc)>1 and not (np.diff(btc.index.asi8)==HOUR.value).all():
        raise DataError("INPUT_MUST_USE_REGULAR_HOURLY_GRID_WITH_NAN_GAPS")
    required = ["open", "high", "low", "close", "volume"]
    if peer is not None and not btc.index.equals(peer.index):
        raise DataError("Unaligned pair candle grids")
    valid = np.isfinite(btc[required].to_numpy(dtype=float)).all(axis=1)
    if peer is not None:
        valid &= np.isfinite(peer[required].to_numpy(dtype=float)).all(axis=1)
    ids = np.flatnonzero(valid)
    if len(ids) == 0:
        return []
    splits = np.where(np.diff(ids) != 1)[0] + 1
    groups = np.split(ids, splits)
    out: list[Signal] = []
    for g in groups:
        if len(g) < 32:
            continue
        lo, hi = int(g[0]), int(g[-1]) + 1
        b = btc.iloc[lo:hi].copy()
        q = peer.iloc[lo:hi].copy() if peer is not None else None
        local = _generate_signals_contiguous(b, q, candidate, config)
        for sig in local:
            sig.index = int(btc.index.get_loc(sig.time))
            out.append(sig)
    return sorted(out, key=lambda x: x.time)

