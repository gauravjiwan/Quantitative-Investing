"""Q3 (assignment pp. 4--5): matched-sample WLS and signal purification.

All inputs describe ONE monthly cross section. They must already share the
same unique stock index; no joining, dropping, filling, or timing inference is
performed. Predictors and ME must be known at actual month-end t, and outcomes
are decimal excess returns in t+1. PS1 month-start labels are not availability
dates. This module does not construct accounting data or historical SIC joins.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


CHARACTERISTICS = ("log_me", "log_bm", "profitability", "investment", "beta")


@dataclass(frozen=True)
class WLSResult:
    coefficients: pd.Series
    fitted: pd.Series
    residuals: pd.Series
    weighted_normal_equations: pd.Series
    objective: float
    rank: int
    condition_number: float
    n_observations: int


@dataclass(frozen=True)
class Q3Design:
    matrix: pd.DataFrame
    objective_weights: pd.Series
    centers: pd.Series
    scales: pd.Series
    unrepresented_industries: tuple[int, ...]
    standardization: str


@dataclass(frozen=True)
class Projection:
    fit: WLSResult
    weighted_r_squared: float
    weighted_signal_variation: float


@dataclass(frozen=True)
class FWLResult:
    projection: Projection
    full: WLSResult
    pure: WLSResult
    slope_difference: float


def _keys(obj, name):
    if not isinstance(obj, (pd.Series, pd.DataFrame)):
        raise TypeError(f"{name} must be a pandas Series or DataFrame")
    if len(obj) == 0 or not obj.index.is_unique or obj.index.to_frame().isna().any().any():
        raise ValueError(f"{name} needs nonempty unique nonnull observation keys")
    if isinstance(obj, pd.DataFrame) and not obj.columns.is_unique:
        raise ValueError(f"{name} has duplicate column names")


def _aligned(reference, **objects):
    _keys(reference, "reference")
    for name, obj in objects.items():
        _keys(obj, name)
        if not obj.index.equals(reference.index):
            raise ValueError(f"{name} must use exactly the same ordered observation keys")


def _finite(obj, name):
    try:
        values = obj.to_numpy(dtype=float, na_value=np.nan)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not np.isfinite(values).all():
        raise ValueError(f"{name} contains missing or nonfinite values; choose the matched sample explicitly")
    return values


def q3_objective_weights(market_cap: pd.Series) -> pd.Series:
    """Footnote 10: objective w=sqrt(ME); row multiplier sqrt(w)=ME**.25."""
    _keys(market_cap, "market_cap")
    if not isinstance(market_cap, pd.Series):
        raise TypeError("market_cap must be a Series")
    me = _finite(market_cap, "market_cap")
    if (me <= 0).any():
        raise ValueError("market capitalization must be strictly positive")
    return pd.Series(np.sqrt(me), index=market_cap.index, name="objective_weight")


def _weights(weights, reference):
    if not isinstance(weights, pd.Series):
        raise TypeError("objective_weights must be a Series")
    _aligned(reference, objective_weights=weights)
    w = _finite(weights, "objective_weights")
    if (w <= 0).any():
        raise ValueError("objective weights must be strictly positive")
    return w


def q3_design(market_cap, book_to_market, profitability, investment, predicted_beta,
              ff12, *, standardization: str) -> Q3Design:
    """Build the prescribed five standardized characteristics plus FF12 dummies.

    ``standardization`` is required: ``equal`` or ``objective_weighted``.
    Both use population dispersion (ddof=0). The assignment does not select a
    standardization convention. Absent industries have no observations and are
    explicitly reported, not fitted as unidentified zero columns. All represented
    industries are included, so the dummy span contains the constant; no separate
    intercept is added. Inputs must be predetermined and matched by the caller.
    """
    if standardization not in ("equal", "objective_weighted"):
        raise ValueError("choose standardization='equal' or 'objective_weighted'")
    inputs = dict(book_to_market=book_to_market, profitability=profitability,
                  investment=investment, predicted_beta=predicted_beta, ff12=ff12)
    if any(not isinstance(x, pd.Series) for x in [market_cap, *inputs.values()]):
        raise TypeError("all Q3 design inputs must be Series")
    _aligned(market_cap, **inputs)
    weights = q3_objective_weights(market_cap)
    me = _finite(market_cap, "market_cap")
    bm = _finite(book_to_market, "book_to_market")
    if (bm <= 0).any():
        raise ValueError("book-to-market must be strictly positive before taking logs")
    industry = _finite(ff12, "ff12")
    if not (np.isin(industry, np.arange(1, 13))).all():
        raise ValueError("FF12 classifications must be integers 1--12; missing classifications need an explicit policy")
    raw = pd.DataFrame(dict(zip(CHARACTERISTICS, [np.log(me), np.log(bm),
        _finite(profitability, "profitability"), _finite(investment, "investment"),
        _finite(predicted_beta, "predicted_beta")])), index=market_cap.index)
    a = np.ones(len(raw)) if standardization == "equal" else weights.to_numpy()
    a = a / a.sum()
    centers = raw.mul(a, axis=0).sum(axis=0)
    centered = raw - centers
    scales = np.sqrt(centered.pow(2).mul(a, axis=0).sum(axis=0))
    # Repeated floating-point values can differ from their computed mean by
    # rounding, yielding a spurious tiny nonzero standard deviation.
    if (raw.max() == raw.min()).any() or (scales <= 0).any() or not np.isfinite(scales).all():
        raise ValueError("a characteristic has zero or nonfinite cross-sectional dispersion")
    dummies = pd.DataFrame({f"ff12_{j:02d}": (industry == j).astype(float)
                            for j in range(1, 13) if np.any(industry == j)}, index=raw.index)
    design = pd.concat([dummies, centered / scales], axis=1)
    return Q3Design(design, weights, centers, scales,
                    tuple(j for j in range(1, 13) if not np.any(industry == j)), standardization)


def wls(y: pd.Series, design: pd.DataFrame, objective_weights: pd.Series) -> WLSResult:
    """Minimize sum(w_i * residual_i**2), using SVD of sqrt(w)*X.

    No automatic intercept; no coefficient inference. Rank-deficient designs
    raise rather than silently selecting one of many coefficient vectors.
    """
    if not isinstance(y, pd.Series) or not isinstance(design, pd.DataFrame):
        raise TypeError("y must be a Series and design a DataFrame")
    _aligned(y, design=design)
    w = _weights(objective_weights, y)
    x, values = _finite(design, "design"), _finite(y, "y")
    if x.shape[1] == 0:
        raise ValueError("design must have at least one column")
    # A common positive rescaling changes neither the minimizer nor the span.
    row_scale = np.sqrt(w / w.max())
    a, b = x * row_scale[:, None], values * row_scale
    coef, _, rank, singular = np.linalg.lstsq(a, b, rcond=None)
    if rank != x.shape[1]:
        raise ValueError("rank-deficient weighted design; check intercept/dummy span and controls")
    fitted = x @ coef
    residual = values - fitted
    normal = x.T @ (w * residual)
    objective = float(np.dot(w, residual * residual))
    if not np.isfinite(np.r_[coef, fitted, residual, normal, objective]).all():
        raise ArithmeticError("nonfinite WLS calculation")
    # Scale the normal-equation error by predictor/outcome norms so the check
    # respects units and does not mistake large ME units for failed projection.
    denominator = np.linalg.norm(a, axis=0) * max(np.linalg.norm(b), np.finfo(float).tiny)
    relative_error = np.abs(a.T @ (residual * row_scale)) / denominator
    if not np.isfinite(relative_error).all() or np.max(relative_error) > 1e-10:
        raise ArithmeticError("weighted orthogonality failed numerical tolerance")
    return WLSResult(pd.Series(coef, index=design.columns, name="coefficient"),
                     pd.Series(fitted, index=y.index, name="fitted"),
                     pd.Series(residual, index=y.index, name="residual"),
                     pd.Series(normal, index=design.columns, name="X_transpose_W_residual"),
                     objective, int(rank), float(singular[0] / singular[-1]), len(y))


def _constant_in_span(controls: pd.DataFrame, weights: pd.Series) -> bool:
    if controls.shape[1] == 0:
        return False
    ones = pd.Series(1., index=controls.index)
    return bool(np.max(np.abs(wls(ones, controls, weights).residuals)) <= 1e-10)


def q3_controls(design: pd.DataFrame, columns, objective_weights: pd.Series) -> pd.DataFrame:
    """Choose controls and add an intercept unless their span already has one.

    Including all represented industry dummies already spans the constant.
    Selecting only some dummies adds an intercept. Redundant supplied controls
    are rejected; the function never silently removes columns or observations.
    """
    _keys(design, "design")
    _weights(objective_weights, design)
    names = list(columns)
    if len(set(names)) != len(names):
        raise ValueError("control column selection must be unique")
    controls = design.loc[:, names].copy()
    if not _constant_in_span(controls, objective_weights):
        if "__intercept__" in controls.columns:
            raise ValueError("reserved intercept column name already present")
        controls.insert(0, "__intercept__", 1.)
    return controls


def residualize(signal: pd.Series, controls: pd.DataFrame,
                objective_weights: pd.Series) -> Projection:
    """Joint projection preserving signal units; require the constant in C's span."""
    fit = wls(signal, controls, objective_weights)
    if not _constant_in_span(controls, objective_weights):
        raise ValueError("Q3 controls must include an intercept or full-industry-dummy span")
    w = _weights(objective_weights, signal)
    z = _finite(signal, "signal")
    centered = z - np.average(z, weights=w)
    variation = float(np.dot(w, centered * centered))
    r_squared = float("nan") if variation == 0 else 1. - fit.objective / variation
    return Projection(fit, r_squared, variation)


def q3_fwl(returns: pd.Series, signal: pd.Series, controls: pd.DataFrame,
           objective_weights: pd.Series) -> FWLResult:
    """Fit [C,z] and [1,z_perp] on identical rows/weights, and verify slopes.

    The equality is algebraic, conditional on these shared inputs, a constant in
    C's span, and nonzero residual signal variation. Fitted returns/residuals
    from the two return regressions generally differ: controls are omitted from
    the second regression. Do not restandardize the projection residual.
    """
    _aligned(returns, signal=signal, controls=controls, objective_weights=objective_weights)
    if "__signal__" in controls.columns:
        raise ValueError("reserved signal column name already present")
    projection = residualize(signal, controls, objective_weights)
    full_x = controls.copy()
    full_x["__signal__"] = signal
    pure_x = pd.DataFrame({"__intercept__": 1., "__signal__": projection.fit.residuals}, index=returns.index)
    full, pure = wls(returns, full_x, objective_weights), wls(returns, pure_x, objective_weights)
    slope = full.coefficients["__signal__"]
    pure_slope = pure.coefficients["__signal__"]
    difference = float(slope - pure_slope)
    if not np.isclose(slope, pure_slope, rtol=1e-8, atol=1e-10):
        raise ArithmeticError("WLS-FWL identity failed numerical tolerance; inspect conditioning")
    return FWLResult(projection, full, pure, difference)
