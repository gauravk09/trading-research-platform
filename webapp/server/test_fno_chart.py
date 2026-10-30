import pandas as pd

from webapp.server.main import _project_intraday_dmas


def test_projected_dma_moves_with_intraday_close_and_finishes_on_daily_sma():
    dates = pd.bdate_range("2025-01-01", periods=210)
    daily = pd.DataFrame({"date": dates, "close": range(1, 211)})
    session = dates[-1].date()
    intraday = pd.DataFrame({"close": [200.0, 205.0, 210.0]})
    days = pd.Series([session, session, session])

    projected = _project_intraday_dmas(intraday, days, daily)

    assert projected["dma10"].is_monotonic_increasing
    assert projected["dma10"].iloc[-1] == daily["close"].tail(10).mean()
    assert projected["dma200"].iloc[-1] == daily["close"].tail(200).mean()


def test_projected_dma_requires_enough_completed_sessions():
    dates = pd.bdate_range("2025-01-01", periods=12)
    daily = pd.DataFrame({"date": dates, "close": range(1, 13)})
    intraday = pd.DataFrame({"close": [12.0]})

    projected = _project_intraday_dmas(intraday, pd.Series([dates[-1].date()]), daily)

    assert projected["dma10"].notna().all()
    assert projected["dma20"].isna().all()
    assert projected["dma50"].isna().all()
    assert projected["dma200"].isna().all()
