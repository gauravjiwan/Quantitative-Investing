"""Per-security OLS market betas from explicitly aligned daily excess returns.

Q1, assignment pages 1--2: beta is covariance / variance, equivalently the
OLS slope WITH an intercept. Inputs must already be decimal excess returns
(e.g. 0.01 = 1%), stock total return minus same-day RF and CRSP VW total
market return minus same-day RF. This module neither constructs RF nor applies
unverified CRSP flag exclusions. No fill, winsorization, or annualization occurs.

Daily dates must be actual observation dates, never PS1 month-start labels.
The caller supplies one security at a time and an actual information cutoff.
Calendar-year windows are (cutoff - DateOffset(years=n), cutoff], including the
cutoff. Leap-day offsets follow pandas calendar arithmetic. This is an explicit
window convention, not a claim that the assignment mandates it.

Research minimum-history rules are unresolved: min_observations is mandatory;
2 is only the mathematical minimum for fitting a nonconstant regressor.
Welch is deliberately not implemented while its exact conventions are unresolved.
"""

from dataclasses import dataclass
from numbers import Integral

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BetaEstimate:
    alpha: float
    beta: float
    status: str
    as_of: pd.Timestamp
    window_start_exclusive: pd.Timestamp | None
    n_window_dates: int
    n_observations: int
    n_unusable_stock: int
    n_unusable_market: int
    first_used_date: pd.Timestamp | None
    last_used_date: pd.Timestamp | None
    market_variance: float


def _daily_series(series: pd.Series, name: str) -> pd.Series:
    if not isinstance(series, pd.Series):
        raise TypeError(f"{name} must be a pandas Series")
    dates = series.index
    if not isinstance(dates, pd.DatetimeIndex):
        raise TypeError(f"{name} must have a DatetimeIndex")
    if dates.tz is not None or dates.hasnans or not dates.equals(dates.normalize()):
        raise ValueError(f"{name} dates must be nonnull, timezone-naive daily dates")
    if dates.has_duplicates:
        raise ValueError(f"{name} has duplicate observation dates")
    return series


def ols_market_beta(
    stock_excess: pd.Series,
    market_excess: pd.Series,
    *,
    as_of,
    min_observations: int,
    years: int | None = None,
) -> BetaEstimate:
    """Estimate one stock's historical beta, with no inputs after ``as_of``.

    ``years`` is 1, 3, or None (all supplied historical dates). Series align
    on exact dates using their union; missing, unmatched, and nonfinite pairs
    are excluded and counted. No source flags are interpreted. ``n_window_dates``
    counts the date union in the window, not an independently supplied trading
    calendar; absence from both series cannot be detected here.

    Insufficient observations or zero market variance return NaN coefficients
    and an explicit status, preserving counts and usable-date bounds. Invalid
    keys/types/configuration raise an exception. Inputs are never modified.
    """
    if isinstance(min_observations, bool) or not isinstance(min_observations, Integral) or min_observations < 2:
        raise ValueError("min_observations must be an explicitly chosen integer >= 2")
    if years is not None and (isinstance(years, bool) or not isinstance(years, Integral) or years not in (1, 3)):
        raise ValueError("years must be 1, 3, or None")
    cutoff = pd.Timestamp(as_of)
    if pd.isna(cutoff) or cutoff.tzinfo is not None or cutoff != cutoff.normalize():
        raise ValueError("as_of must be a nonnull, timezone-naive daily date")
    lower = None if years is None else cutoff - pd.DateOffset(years=int(years))
    stock = _daily_series(stock_excess, "stock_excess")
    market = _daily_series(market_excess, "market_excess")

    def select(series):
        mask = series.index <= cutoff
        if lower is not None:
            mask &= series.index > lower
        return series.loc[mask]

    paired = pd.concat([select(stock).rename("stock"), select(market).rename("market")], axis=1).sort_index()
    values = paired.to_numpy(dtype=float, na_value=np.nan)
    usable = np.isfinite(values)
    complete = usable.all(axis=1)
    sample = values[complete]
    used_dates = paired.index[complete]
    count = len(sample)
    status = "insufficient_history" if count < min_observations else "ok"
    alpha = beta = variance = float("nan")
    if count >= 2:
        y, x = sample[:, 0], sample[:, 1]
        xc, yc = x - x.mean(), y - y.mean()
        # A repeated floating-point value can differ from its computed mean by
        # rounding; detect the truly constant regressor before dividing.
        ssx = 0.0 if np.all(x == x[0]) else float(xc @ xc)
        variance = ssx / (count - 1)
        if status == "ok":
            if ssx == 0:
                status = "zero_market_variance"
            elif not np.isfinite(ssx) or not np.isfinite(float(xc @ yc)):
                status = "numerical_failure"
            else:
                beta = float((xc @ yc) / ssx)
                alpha = float(y.mean() - beta * x.mean())
                if not np.isfinite(alpha) or not np.isfinite(beta):
                    status = "numerical_failure"
                    alpha = beta = float("nan")
    return BetaEstimate(
        alpha, beta, status, cutoff, lower, len(paired), count,
        int((~usable[:, 0]).sum()), int((~usable[:, 1]).sum()),
        used_dates.min() if count else None,
        used_dates.max() if count else None, variance,
    )


def one_year_beta(stock_excess, market_excess, *, as_of, min_observations):
    return ols_market_beta(stock_excess, market_excess, as_of=as_of,
                           min_observations=min_observations, years=1)


def three_year_beta(stock_excess, market_excess, *, as_of, min_observations):
    return ols_market_beta(stock_excess, market_excess, as_of=as_of,
                           min_observations=min_observations, years=3)


def expanding_beta(stock_excess, market_excess, *, as_of, min_observations):
    return ols_market_beta(stock_excess, market_excess, as_of=as_of,
                           min_observations=min_observations)
