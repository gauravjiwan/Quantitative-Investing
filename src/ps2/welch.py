"""Welch (2022) Appendix A kernel and explicit historical-data adapter.

See docs/ps2_welch_method.md for source evidence and unresolved sample policies.
Inputs are decimal daily excess total returns, already aligned with same-day RF.
This module does not interpret CRSP flags or declare a production sample eligible.
"""

from dataclasses import dataclass
from numbers import Integral

import numpy as np
import pandas as pd

from .betas import _daily_series


APPENDIX_RHO = 2.0 / 256.0


def slope_winsorize(stock_excess, market_excess):
    """Clip stock excess returns between min(-2*x,4*x) and max(-2*x,4*x).

    Negative-market bounds are reordered; a zero market return implies zero
    winsorized stock return. Invalid pairs must be handled explicitly upstream.
    """
    y, x = np.asarray(stock_excess, dtype=float), np.asarray(market_excess, dtype=float)
    if y.ndim != 1 or x.shape != y.shape or not np.isfinite(y).all() or not np.isfinite(x).all():
        raise ValueError("returns must be equally sized finite one-dimensional arrays")
    return np.clip(y, np.minimum(-2 * x, 4 * x), np.maximum(-2 * x, 4 * x))


def appendix_weights(n: int, *, rho: float):
    """Appendix A objective weights; callers must explicitly choose decay rho.

    The Appendix specifies 2/256, conflicting with 2/252 in the introduction.
    ``APPENDIX_RHO`` is a documented reference constant, never an implicit default.
    """
    if isinstance(n, bool) or not isinstance(n, Integral) or n < 0:
        raise ValueError("n must be a nonnegative integer")
    if isinstance(rho, (bool, str)) or not np.isscalar(rho) or not np.isfinite(rho) or rho < 0:
        raise ValueError("rho must be an explicitly chosen finite nonnegative scalar")
    return np.exp(-float(rho) * np.arange(n, 0, -1, dtype=float))


@dataclass(frozen=True)
class WelchFit:
    alpha: float
    beta: float
    status: str
    n_observations: int
    n_clipped: int
    weight_sum: float


def welch_from_pairs(stock_excess, market_excess, *, rho: float) -> WelchFit:
    """Exact finite-pair Appendix A BSW/BSWA regression, including an intercept.

    This low-level kernel has only the mathematical two-pair requirement. It
    is not an implementation of the paper's empirical eligibility filters.
    Pairs must already be sorted oldest to newest; dates cannot be inferred here.
    """
    y, x = np.asarray(stock_excess, dtype=float), np.asarray(market_excess, dtype=float)
    clipped = slope_winsorize(y, x)
    w = appendix_weights(len(x), rho=rho)
    return _fit(y, x, clipped, w)


def _fit(y, x, clipped, w):
    n = len(x)
    nan = float("nan")
    count = int(np.count_nonzero(y != clipped))
    if n < 2:
        return WelchFit(nan, nan, "insufficient_history", n, count, float(w.sum()))
    weight_sum = float(w.sum())
    if not np.isfinite(weight_sum) or weight_sum <= 0:
        return WelchFit(nan, nan, "numerical_failure", n, count, weight_sum)
    if np.all(x == x[0]):
        return WelchFit(nan, nan, "zero_market_variance", n, count, float(w.sum()))
    xm, ym = np.average(x, weights=w), np.average(clipped, weights=w)
    xc, yc = x - xm, clipped - ym
    denominator = float(w @ (xc * xc))
    numerator = float(w @ (xc * yc))
    if denominator <= 0 or not np.isfinite(denominator) or not np.isfinite(numerator):
        return WelchFit(nan, nan, "numerical_failure", n, count, float(w.sum()))
    beta = numerator / denominator
    alpha = float(ym - beta * xm)
    status = "ok" if np.isfinite(alpha) and np.isfinite(beta) else "numerical_failure"
    return WelchFit(alpha if status == "ok" else nan, beta if status == "ok" else nan,
                    status, n, count, float(w.sum()))


@dataclass(frozen=True)
class HistoricalWelchEstimate:
    fit: WelchFit
    as_of: pd.Timestamp
    age_basis: str
    rho: float
    min_observations: int
    require_current_return: bool
    n_calendar_dates: int
    n_unusable_stock: int
    n_unusable_market: int
    first_used_date: pd.Timestamp | None
    last_used_date: pd.Timestamp | None
    last_market_date: pd.Timestamp | None
    current_return_available: bool


def historical_welch_beta(
    stock_excess: pd.Series, market_excess: pd.Series, *, as_of,
    trading_calendar: pd.DatetimeIndex, min_observations: int,
    require_current_return: bool, age_basis: str, rho: float,
) -> HistoricalWelchEstimate:
    """Age-weighted beta from all supplied history through an actual cutoff.

    Required policies prevent silently choosing PS2 eligibility or missing-date
    aging. ``valid_pairs`` ages the regression's complete pairs by row position;
    ``market_calendar`` retains elapsed supplied trading sessions across gaps.
    Neither choice is claimed to resolve the paper's missing-date ambiguity.
    An explicit calendar identifies the last trading date before a weekend end.
    Missing/nonfinite pairs are excluded and counted, without filling returns.
    No rolling history cutoff, flag filter, or shrinkage is applied.
    """
    if isinstance(min_observations, bool) or not isinstance(min_observations, Integral) or min_observations < 2:
        raise ValueError("min_observations must be an explicitly chosen integer >= 2")
    if not isinstance(require_current_return, bool):
        raise ValueError("require_current_return must be bool")
    if age_basis not in ("valid_pairs", "market_calendar"):
        raise ValueError("age_basis must explicitly be valid_pairs or market_calendar")
    cutoff = pd.Timestamp(as_of)
    if pd.isna(cutoff) or cutoff.tzinfo is not None or cutoff != cutoff.normalize():
        raise ValueError("as_of must be a nonnull timezone-naive daily date")
    if not isinstance(trading_calendar, pd.DatetimeIndex):
        raise TypeError("trading_calendar must be a DatetimeIndex")
    _daily_series(pd.Series(index=trading_calendar, dtype=float), "trading_calendar")
    calendar = trading_calendar[trading_calendar <= cutoff].sort_values()
    stock = _daily_series(stock_excess, "stock_excess")
    market = _daily_series(market_excess, "market_excess")
    for series in (stock, market):
        if not series.index[series.index <= cutoff].isin(calendar).all():
            raise ValueError("historical observation date absent from supplied trading calendar")
    values = pd.concat([stock.reindex(calendar), market.reindex(calendar)], axis=1).to_numpy(dtype=float, na_value=np.nan)
    usable = np.isfinite(values)
    valid = usable.all(axis=1)
    dates = calendar[valid]
    y, x = values[valid, 0], values[valid, 1]
    clipped = slope_winsorize(y, x)
    all_weights = appendix_weights(len(calendar), rho=rho)
    weights = (appendix_weights(len(x), rho=rho) if age_basis == "valid_pairs" else all_weights[valid])
    current = bool(len(calendar) and valid[-1])
    if len(x) < min_observations or (require_current_return and not current):
        status = "insufficient_history" if len(x) < min_observations else "missing_current_return"
        fit = WelchFit(float("nan"), float("nan"), status, len(x), int(np.count_nonzero(y != clipped)), float(weights.sum()))
    else:
        fit = _fit(y, x, clipped, weights)
    return HistoricalWelchEstimate(
        fit, cutoff, age_basis, float(rho), int(min_observations), require_current_return,
        len(calendar), int((~usable[:, 0]).sum()), int((~usable[:, 1]).sum()),
        dates.min() if len(dates) else None, dates.max() if len(dates) else None,
        calendar.max() if len(calendar) else None, current,
    )
