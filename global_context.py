"""Global overnight context for Alpha Radar V16.8.

This module is downstream of the frozen Taiwan stock-selection model.  It does
not change short/mid/long selection scores.  It measures external overnight
stress and, together with Taiwan intraday resilience, can enable a small
"panic-reversal" entry when a high-quality stock is sold down by a broad shock
but starts absorbing the pressure.

Data is best-effort.  If Yahoo/yfinance is unavailable, the caller receives an
explicit unavailable context and the Taiwan-only model continues unchanged.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception:  # pragma: no cover - deployment dependency is optional at import
    yf = None

from strategy_config import GLOBAL_OVERNIGHT_POLICY


SYMBOLS = {
    "sox": "^SOX",
    "ndx": "^NDX",
    "spx": "^GSPC",
    "tsm_adr": "TSM",
    "vix": "^VIX",
    "nq_fut": "NQ=F",
    "es_fut": "ES=F",
    "tnx": "^TNX",
    "dxy": "DX-Y.NYB",
}


def _taipei_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8)))


def _f(v, default=None):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _clip01(x: float) -> float:
    return float(np.clip(float(x), 0.0, 1.0))


def _decline_risk(ret_pct: float | None, scale_pct: float) -> float | None:
    if ret_pct is None:
        return None
    return _clip01(max(0.0, -float(ret_pct)) / max(float(scale_pct), 1e-9)) * 100.0


def _rise_risk(ret_pct: float | None, scale_pct: float) -> float | None:
    if ret_pct is None:
        return None
    return _clip01(max(0.0, float(ret_pct)) / max(float(scale_pct), 1e-9)) * 100.0


def compute_global_context(
    returns_pct: dict[str, float | None],
    *,
    asof: str = "",
    source: str = "synthetic/input",
) -> dict:
    """Compute a bounded overnight stress score from already-computed returns.

    Returns are percentage points, e.g. ``-3.2`` means -3.2%.
    Missing factors are re-normalized rather than treated as zero risk.
    """
    cfg = GLOBAL_OVERNIGHT_POLICY
    weights = cfg["weights"]
    scales = cfg["risk_scale_pct"]
    components: dict[str, dict[str, Any]] = {}
    weighted = 0.0
    available_weight = 0.0

    for key, weight in weights.items():
        val = _f(returns_pct.get(key))
        if val is None:
            continue
        if key in {"vix", "tnx", "dxy"}:
            risk = _rise_risk(val, scales[key])
        else:
            risk = _decline_risk(val, scales[key])
        if risk is None:
            continue
        weighted += float(weight) * float(risk)
        available_weight += float(weight)
        components[key] = {"return_pct": round(val, 3), "risk": round(float(risk), 1), "weight": float(weight)}

    if available_weight < float(cfg.get("min_available_weight", 0.45)):
        return {
            "available": False,
            "shock_score": None,
            "mode": "UNKNOWN",
            "position_multiplier": 1.0,
            "panic_mode": False,
            "returns_pct": {k: _f(v) for k, v in returns_pct.items()},
            "components": components,
            "coverage_weight": round(available_weight, 3),
            "asof": asof,
            "source": source,
            "reason": "INSUFFICIENT_GLOBAL_FACTORS",
        }

    raw_shock = weighted / available_weight

    # If US index futures recover before Taiwan opens/trades, reduce—but never
    # erase—the previous-session shock.  A relief rally is confirmation, not a
    # reason to pretend the overnight selloff did not happen.
    relief = 0.0
    nq = _f(returns_pct.get("nq_fut"))
    es = _f(returns_pct.get("es_fut"))
    if nq is not None and nq > 0:
        relief += min(float(cfg.get("max_relief_points", 14.0)) * 0.70, nq / 1.5 * 9.0)
    if es is not None and es > 0:
        relief += min(float(cfg.get("max_relief_points", 14.0)) * 0.30, es / 1.2 * 4.0)
    relief = float(np.clip(relief, 0.0, float(cfg.get("max_relief_points", 14.0))))
    shock = float(np.clip(raw_shock - relief, 0.0, 100.0))

    panic_threshold = float(cfg["panic_threshold"])
    stress_threshold = float(cfg["stress_threshold"])
    if shock >= panic_threshold:
        mode = "PANIC"
    elif shock >= stress_threshold:
        mode = "STRESS"
    else:
        mode = "NORMAL"

    bands = cfg["position_multiplier"]
    if shock >= float(bands["severe_at"]):
        position_mult = float(bands["severe"])
    elif shock >= float(bands["panic_at"]):
        position_mult = float(bands["panic"])
    elif shock >= float(bands["stress_at"]):
        position_mult = float(bands["stress"])
    else:
        position_mult = 1.0

    return {
        "available": True,
        "shock_score": round(shock, 1),
        "raw_shock_score": round(float(raw_shock), 1),
        "relief_points": round(relief, 1),
        "mode": mode,
        "position_multiplier": position_mult,
        "panic_mode": bool(shock >= panic_threshold),
        "returns_pct": {k: _f(v) for k, v in returns_pct.items()},
        "components": components,
        "coverage_weight": round(available_weight, 3),
        "asof": asof,
        "source": source,
        "reason": "",
    }


def _extract_close_frame(data: pd.DataFrame, symbol: str, symbols: list[str]) -> pd.Series:
    if data is None or data.empty:
        return pd.Series(dtype=float)
    try:
        if isinstance(data.columns, pd.MultiIndex):
            lvl0 = set(map(str, data.columns.get_level_values(0)))
            lvl1 = set(map(str, data.columns.get_level_values(1)))
            if symbol in lvl0:
                frame = data[symbol]
                s = frame["Close"] if "Close" in frame.columns else pd.Series(dtype=float)
            elif symbol in lvl1:
                frame = data.xs(symbol, axis=1, level=1)
                s = frame["Close"] if "Close" in frame.columns else pd.Series(dtype=float)
            else:
                return pd.Series(dtype=float)
        else:
            if len(symbols) != 1 or "Close" not in data.columns:
                return pd.Series(dtype=float)
            s = data["Close"]
        return pd.to_numeric(s, errors="coerce").dropna()
    except Exception:
        return pd.Series(dtype=float)


def _download_returns() -> tuple[dict[str, float | None], str]:
    if yf is None:
        raise RuntimeError("yfinance unavailable")
    symbols = list(SYMBOLS.values())
    data = yf.download(
        symbols,
        period="12d",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=True,
        timeout=12,
    )
    returns: dict[str, float | None] = {}
    last_dates: list[pd.Timestamp] = []
    for key, symbol in SYMBOLS.items():
        s = _extract_close_frame(data, symbol, symbols)
        if len(s) >= 2 and float(s.iloc[-2]) > 0:
            returns[key] = float((s.iloc[-1] / s.iloc[-2] - 1.0) * 100.0)
            try:
                last_dates.append(pd.Timestamp(s.index[-1]))
            except Exception:
                pass
        else:
            returns[key] = None
    # Refresh NQ/ES with a current intraday print when available.  Compare the
    # latest 5-minute price with the previous completed daily close, so Taiwan
    # morning can see whether US futures are recovering or extending the shock.
    try:
        fut_symbols = [SYMBOLS["nq_fut"], SYMBOLS["es_fut"]]
        intraday = yf.download(
            fut_symbols, period="2d", interval="5m", group_by="ticker",
            auto_adjust=True, actions=False, progress=False, threads=True, timeout=8,
        )
        for key in ("nq_fut", "es_fut"):
            symbol = SYMBOLS[key]
            intr = _extract_close_frame(intraday, symbol, fut_symbols)
            daily = _extract_close_frame(data, symbol, symbols)
            if len(intr) and len(daily) >= 2 and float(daily.iloc[-2]) > 0:
                returns[key] = float((intr.iloc[-1] / daily.iloc[-2] - 1.0) * 100.0)
    except Exception:
        pass

    asof = max(last_dates).date().isoformat() if last_dates else ""
    return returns, asof


def fetch_global_context(
    data_dir: Path,
    *,
    now: _dt.datetime | None = None,
    max_age_minutes: int | None = None,
    force: bool = False,
) -> dict:
    """Best-effort cached global context for Streamlit execution pages."""
    now = now or _taipei_now()
    cfg = GLOBAL_OVERNIGHT_POLICY
    if os.getenv("ALPHA_RADAR_DISABLE_GLOBAL_NETWORK", "0") == "1":
        return {
            "available": False, "shock_score": None, "mode": "UNKNOWN",
            "position_multiplier": 1.0, "panic_mode": False, "returns_pct": {},
            "components": {}, "coverage_weight": 0.0, "asof": "",
            "fetched_at": now.isoformat(timespec="seconds"), "source": "",
            "reason": "GLOBAL_NETWORK_DISABLED",
        }
    max_age_minutes = int(max_age_minutes or cfg.get("cache_minutes", 10))
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache = data_dir / "global_context.json"

    if not force and cache.exists():
        try:
            obj = json.loads(cache.read_text(encoding="utf-8"))
            ts = _dt.datetime.fromisoformat(str(obj.get("fetched_at") or ""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=8)))
            if (now - ts).total_seconds() <= max_age_minutes * 60:
                return obj
        except Exception:
            pass

    try:
        returns, asof = _download_returns()
        obj = compute_global_context(returns, asof=asof, source="Yahoo Finance / yfinance")
        obj["fetched_at"] = now.isoformat(timespec="seconds")
        try:
            cache.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return obj
    except Exception as exc:
        # A stale successful cache is preferable to inventing zeros, but it is
        # explicitly marked stale so the UI/model can avoid treating it as a
        # fresh panic trigger.
        if cache.exists():
            try:
                obj = json.loads(cache.read_text(encoding="utf-8"))
                obj = dict(obj)
                obj["stale"] = True
                obj["reason"] = f"GLOBAL_REFRESH_FAILED:{type(exc).__name__}"
                return obj
            except Exception:
                pass
        return {
            "available": False,
            "shock_score": None,
            "mode": "UNKNOWN",
            "position_multiplier": 1.0,
            "panic_mode": False,
            "returns_pct": {},
            "components": {},
            "coverage_weight": 0.0,
            "asof": "",
            "fetched_at": now.isoformat(timespec="seconds"),
            "source": "",
            "reason": f"GLOBAL_REFRESH_FAILED:{type(exc).__name__}",
        }
