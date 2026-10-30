"""Read-only API for the standalone SBI Contra Fund research dashboard."""

import math
import os
from functools import lru_cache

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

from fund_behavior_study import STORE, build_study, company_study


router = APIRouter(prefix="/api/fund-study", tags=["fund-study"])


def _safe(value):
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _mtime() -> float:
    try:
        return os.path.getmtime(STORE)
    except FileNotFoundError:
        return 0.0


@lru_cache(maxsize=8)
def _overview(years: int, mtime: float):
    return _safe(build_study(years))


@lru_cache(maxsize=64)
def _company(symbol: str, years: int, mtime: float):
    return _safe(company_study(symbol, years))


@router.get("/overview")
def overview(years: int = 3):
    if not os.path.exists(STORE):
        raise HTTPException(503, "Fund study data missing; run the focused collector")
    return _overview(max(1, min(5, years)), _mtime())


@router.get("/company/{symbol}")
def company(symbol: str, years: int = 3):
    if not os.path.exists(STORE):
        raise HTTPException(503, "Fund study data missing; run the focused collector")
    result = _company(symbol.strip().upper(), max(1, min(5, years)), _mtime())
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result
