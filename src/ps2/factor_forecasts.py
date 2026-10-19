"""Q2 (assignment pp. 3--4): isolated monthly, timing-safe forecast primitives.

Returns are decimals and inputs must be supplied as genuinely available monthly
observations. A monthly PeriodIndex labels an observation month, not a release
date. The caller remains responsible for release lags and point-in-time data.
No source data, RF, eligibility, share-class, or beta-window convention is chosen
here. Missing and nonfinite observations are counted rather than filled.
"""
from dataclasses import dataclass
from numbers import Integral
from typing import Mapping

import numpy as np
import pandas as pd


FACTORS = ("Mkt-RF", "HML", "SMB")


@dataclass(frozen=True)
class JointExposure:
    as_of: pd.Period
    alpha: float
    beta: pd.Series
    status: str
    n_window_months: int
    n_observations: int
    n_incomplete: int
    first_used_month: pd.Period | None
    last_used_month: pd.Period | None


@dataclass(frozen=True)
class PremiumForecast:
    as_of: pd.Period
    target_month: pd.Period
    value: pd.Series
    status: str
    n_candidates: int
    n_observations: int
    n_incomplete: int
    last_outcome_month: pd.Period | None


def _month(value) -> pd.Period:
    if not isinstance(value, pd.Period) or value.freqstr != "M" or pd.isna(value):
        raise ValueError("month must be an explicit nonnull monthly Period")
    return value


def _monthly(obj, name):
    if not isinstance(obj, (pd.Series, pd.DataFrame)):
        raise TypeError(f"{name} must be a Series or DataFrame")
    index = obj.index
    if not isinstance(index, pd.PeriodIndex) or index.freqstr != "M":
        raise ValueError(f"{name} requires a monthly PeriodIndex; dates are not availability dates")
    if index.hasnans or index.has_duplicates:
        raise ValueError(f"{name} has null or duplicate months")
    if isinstance(obj, pd.DataFrame) and obj.columns.has_duplicates:
        raise ValueError(f"{name} has duplicate columns")
    return obj.sort_index().astype(float)


def _minimum(value, lower=1):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < lower:
        raise ValueError(f"min_observations must be an explicitly chosen integer >= {lower}")


def _factors(frame):
    frame = _monthly(frame, "factors")
    if not isinstance(frame, pd.DataFrame) or set(frame.columns) != set(FACTORS):
        raise ValueError(f"factors require exactly {FACTORS}")
    return frame.loc[:, list(FACTORS)]


def joint_factor_exposure(stock_excess, factors, *, as_of, min_observations,
                          window_months, fit_intercept):
    """Joint monthly OLS, using all three traded factors on identical rows.

    Window is (as_of-window_months, as_of], or supplied expanding history for
    None. Window/minimum/intercept choices are explicit pending research design.
    The intercept, when fitted, is a nuisance term: Q2 forecasts omit alpha.
    Rank deficiency returns missing betas rather than a pseudoinverse estimate.
    """
    cutoff = _month(as_of)
    if not isinstance(fit_intercept, bool):
        raise ValueError("fit_intercept must explicitly be True or False")
    width = 3 + int(fit_intercept)
    _minimum(min_observations, width)
    if window_months is not None:
        if isinstance(window_months, bool) or not isinstance(window_months, Integral) or window_months < 1:
            raise ValueError("window_months must explicitly be a positive integer or None")
    y = _monthly(stock_excess, "stock_excess")
    if not isinstance(y, pd.Series):
        raise TypeError("stock_excess must be a Series")
    x = _factors(factors)
    # Restrict before pairing or checking values: future outcomes never train.
    def select(obj):
        mask = obj.index <= cutoff
        if window_months is not None:
            mask &= obj.index > cutoff - int(window_months)
        return obj.loc[mask]
    paired = pd.concat([select(y).rename("stock_excess"), select(x)], axis=1).sort_index()
    valid = np.isfinite(paired.to_numpy()).all(axis=1)
    complete = paired.loc[valid]
    beta = pd.Series(np.nan, index=FACTORS, dtype=float)
    alpha = float("nan")
    status = "insufficient_history"
    if len(complete) >= min_observations:
        design = complete.loc[:, list(FACTORS)].to_numpy()
        if fit_intercept:
            design = np.column_stack([np.ones(len(design)), design])
        coef, _, rank, _ = np.linalg.lstsq(design, complete.stock_excess.to_numpy(), rcond=None)
        status = "ok" if rank == width else "rank_deficient"
        if status == "ok":
            alpha = float(coef[0]) if fit_intercept else 0.0
            beta[:] = coef[int(fit_intercept):]
    return JointExposure(cutoff, alpha, beta, status, len(paired), len(complete),
                         int((~valid).sum()), complete.index.min() if len(complete) else None,
                         complete.index.max() if len(complete) else None)


def expanding_mean_forecast(returns, *, as_of, min_observations):
    """Next-month arithmetic mean using observations no later than month-end t.

    A Series supports the CRSP VW excess-return baseline; a factor DataFrame
    supports the premium baseline. Multiple series use common complete months,
    explicitly counted, so factor means share one estimation sample.
    """
    cutoff = _month(as_of)
    _minimum(min_observations)
    history = _monthly(returns, "returns")
    if isinstance(history, pd.Series):
        history = history.rename(history.name or "mean").to_frame()
    if history.shape[1] == 0:
        raise ValueError("returns must include at least one series")
    history = history.loc[history.index <= cutoff]
    valid = np.isfinite(history.to_numpy()).all(axis=1)
    sample = history.loc[valid]
    status = "ok" if len(sample) >= min_observations else "insufficient_history"
    value = sample.mean() if status == "ok" else pd.Series(np.nan, index=history.columns)
    return PremiumForecast(cutoff, cutoff+1, value, status, len(history), len(sample),
                           int((~valid).sum()), sample.index.max() if len(sample) else None)


def expanding_predictive_forecast(factors, predictors, *, as_of, min_observations):
    """Configured alternative: expanding joint OLS of F[s+1] on [1, Z[s]].

    Z must already be available at the end of its labeled month. Training uses
    only outcomes through t; target-month returns are never read for fitting.
    Calendar pairing is exactly s+1, never a row shift across missing months.
    Economic predictors and any transformations must be fixed in sample by the
    caller. This is machinery for a candidate, not a claimed superior model.
    """
    cutoff = _month(as_of)
    outcomes = _factors(factors)
    features = _monthly(predictors, "predictors")
    if not isinstance(features, pd.DataFrame) or features.shape[1] == 0:
        raise ValueError("predictors must be a nonempty DataFrame")
    _minimum(min_observations, features.shape[1]+1)
    # Origin s is strictly earlier than t so the latest training outcome is t.
    train_x = features.loc[features.index < cutoff].copy()
    train_x.index = train_x.index + 1
    train_y = outcomes.loc[outcomes.index <= cutoff]
    candidate = pd.concat({"x": train_x, "y": train_y}, axis=1).sort_index()
    valid = np.isfinite(candidate.to_numpy()).all(axis=1)
    sample = candidate.loc[valid]
    value = pd.Series(np.nan, index=FACTORS, dtype=float)
    status = "insufficient_history"
    current = features.reindex(pd.PeriodIndex([cutoff], freq="M")).to_numpy()[0]
    if not np.isfinite(current).all():
        status = "missing_current_predictors"
    elif len(sample) >= min_observations:
        design = np.column_stack([np.ones(len(sample)), sample["x"].to_numpy()])
        coef, _, rank, _ = np.linalg.lstsq(design, sample["y"].to_numpy(), rcond=None)
        status = "ok" if rank == design.shape[1] else "rank_deficient"
        if status == "ok":
            value[:] = np.r_[1.0, current] @ coef
    return PremiumForecast(cutoff, cutoff+1, value, status, len(candidate), len(sample),
                           int((~valid).sum()), sample.index.max() if len(sample) else None)


def stock_return_forecasts(exposures: Mapping, premium_methods: Mapping[str, PremiumForecast],
                           crsp_mean: PremiumForecast):
    """Use the identical joint beta snapshot for every premium method.

    No fitted alpha enters beta'lambda (assignment p. 3). The separate CRSP
    benchmark broadcasts its expanding mean excess return to every security.
    Missing coefficient/forecast statuses remain missing, for common matching
    downstream; no stock is silently replaced by another forecasting rule.
    """
    if len(crsp_mean.value) != 1:
        raise ValueError("CRSP mean must contain exactly one excess-return series")
    if not premium_methods or "crsp_mean" in premium_methods:
        raise ValueError("premium methods must be nonempty and cannot use reserved crsp_mean")
    cutoff = crsp_mean.as_of
    methods = list(premium_methods)
    for forecast in premium_methods.values():
        if forecast.as_of != cutoff or forecast.target_month != cutoff+1:
            raise ValueError("premium forecasts must have identical information and target months")
        if set(forecast.value.index) != set(FACTORS):
            raise ValueError("premium forecast factors must match joint exposures")
    if crsp_mean.target_month != cutoff+1:
        raise ValueError("CRSP target must be the following calendar month")
    rows = []
    for security, exposure in exposures.items():
        if exposure.as_of != cutoff or set(exposure.beta.index) != set(FACTORS):
            raise ValueError("exposure information month and factors must match forecasts")
        row = {"security": security, "forecast_month": cutoff, "month": cutoff+1}
        for method in methods:
            forecast = premium_methods[method]
            row[method] = (float(exposure.beta.loc[list(FACTORS)] @ forecast.value.loc[list(FACTORS)])
                           if exposure.status == forecast.status == "ok" else np.nan)
        row["crsp_mean"] = float(crsp_mean.value.iloc[0]) if crsp_mean.status == "ok" else np.nan
        rows.append(row)
    return pd.DataFrame(rows, columns=["security", "forecast_month", "month", *methods, "crsp_mean"])


def matched_monthly_losses(panel, *, forecast_columns, actual_column, weight_column):
    """Common stock-month MSE, normalized within month before time averaging.

    Required keys are security and monthly Period month (realization month).
    One positive finite beginning-of-return-month weight is shared by every
    method; weight_column=None selects EW. Missing actual/forecasts/weights are
    excluded once, jointly, and retained in monthly counts. Duplicate/null keys
    or negative/zero finite supplied weights are errors, never auto-corrected.
    """
    models = list(forecast_columns)
    if not models or len(set(models)) != len(models):
        raise ValueError("forecast_columns must be nonempty and unique")
    keys = panel[["security", "month"]]
    if keys.isna().any().any() or keys.duplicated().any():
        raise ValueError("null or duplicate stock-month keys")
    for month in keys.month:
        _month(month)
    if actual_column in models:
        raise ValueError("actual_column cannot be a forecast")
    values = panel[[actual_column, *models]].to_numpy(dtype=float)
    weight = np.ones(len(panel)) if weight_column is None else panel[weight_column].to_numpy(dtype=float)
    if (np.isfinite(weight) & (weight <= 0)).any():
        raise ValueError("finite weights must be positive")
    valid = np.isfinite(values).all(axis=1) & np.isfinite(weight)
    rows = []
    for month in sorted(keys.month.unique()):
        present = keys.month.to_numpy() == month
        take = present & valid
        row = {"month": month, "n_candidates": int(present.sum()), "n_matched": int(take.sum()),
               "n_excluded": int((present & ~valid).sum())}
        for j, model in enumerate(models, 1):
            row[model] = float(np.average((values[take, 0]-values[take, j])**2, weights=weight[take])) if take.any() else np.nan
        rows.append(row)
    return pd.DataFrame(rows, columns=["month", "n_candidates", "n_matched", "n_excluded", *models])


def evaluate_loss_periods(losses, *, model_columns, benchmark, first_oos_month):
    """Equal-month IS/OOS MSE and pseudo-R2 from already matched monthly losses.

    The split must be preselected, supplied explicitly as a monthly Period.
    No automatic split selection or tuning occurs. Zero benchmark MSE yields
    undefined pseudo-R2, reported as NaN with an explicit status.
    """
    split = _month(first_oos_month)
    models = list(model_columns)
    if not models or len(set(models)) != len(models) or benchmark not in models:
        raise ValueError("unique model_columns must include the benchmark")
    if losses.month.isna().any() or losses.month.duplicated().any():
        raise ValueError("monthly losses require nonnull unique months")
    for month in losses.month:
        _month(month)
    values = losses[models].to_numpy(dtype=float)
    if (np.isfinite(values) & (values < 0)).any():
        raise ValueError("losses cannot be negative")
    finite = np.isfinite(values).all(axis=1)
    rows = []
    for label, mask in (("in_sample", losses.month < split), ("out_of_sample", losses.month >= split)):
        use = np.asarray(mask) & finite
        mean = losses.loc[use, models].mean()
        base = mean[benchmark]
        for model in models:
            status = "no_matched_months" if not use.any() else "zero_benchmark_mse" if base == 0 else "ok"
            rows.append({"period": label, "model": model, "n_candidate_months": int(mask.sum()),
                         "n_months": int(use.sum()), "mse": mean[model],
                         "pseudo_r2": 1-mean[model]/base if status == "ok" else np.nan, "status": status})
    return pd.DataFrame(rows)


def paired_loss_inference(losses, *, model, benchmark, newey_west_lags):
    """Bartlett Newey--West SE of monthly mean(model loss - benchmark loss).

    Bandwidth is mandatory, no finite-sample correction. Requires contiguous,
    complete monthly losses so row lags are calendar lags. The caller evaluates
    IS and OOS separately. Normal-reference t statistics are descriptive, without
    claiming a nested-model forecast comparison correction.
    """
    if (isinstance(newey_west_lags, bool) or not isinstance(newey_west_lags, Integral)
            or newey_west_lags < 0):
        raise ValueError("newey_west_lags must be an explicitly chosen integer >= 0")
    frame = losses[["month", model, benchmark]].copy().sort_values("month")
    for month in frame.month:
        _month(month)
    n = len(frame)
    if n < 2 or newey_west_lags >= n:
        raise ValueError("at least two months and fewer lags than observations required")
    expected = pd.period_range(frame.month.iloc[0], frame.month.iloc[-1], freq="M")
    if list(frame.month) != list(expected):
        raise ValueError("paired inference requires unique contiguous calendar months")
    data = frame[[model, benchmark]].to_numpy(dtype=float)
    if not np.isfinite(data).all() or (data < 0).any():
        raise ValueError("paired inference requires complete finite nonnegative losses")
    differences = data[:, 0]-data[:, 1]
    mean = float(differences.mean())
    centered = differences-mean
    long_run_variance = float(centered @ centered / n)
    for lag in range(1, int(newey_west_lags)+1):
        gamma = float(centered[lag:] @ centered[:-lag] / n)
        long_run_variance += 2*(1-lag/(newey_west_lags+1))*gamma
    se = float(np.sqrt(max(long_run_variance, 0.0)/n))
    return {"n_months": n, "mean_loss_difference": mean, "newey_west_lags": int(newey_west_lags),
            "standard_error": se, "t_statistic": mean/se if se > 0 else np.nan,
            "status": "ok" if se > 0 else "zero_standard_error"}
