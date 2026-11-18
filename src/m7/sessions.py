"""NYSE trading sessions: which days should have prices, and when each day's close is final."""

import datetime as dt

import pandas as pd

MARKET_TZ = "America/New_York"
SETTLE = pd.Timedelta(minutes=30)  # Yahoo's closing prices are final a little after the close

_CAL = None


def calendar():
    global _CAL
    if _CAL is None:
        import exchange_calendars as xc

        _CAL = xc.get_calendar("XNYS", start="2021-01-01")
    return _CAL


def sessions_between(first, last):
    """Every NYSE session from `first` to `last`, inclusive."""
    return pd.DatetimeIndex(calendar().sessions_in_range(pd.Timestamp(first), pd.Timestamp(last)), name="Date")


def settled_at(session):
    """When a session's closing prices can be trusted (handles 1pm early closes)."""
    return calendar().session_close(pd.Timestamp(session)) + SETTLE


def expected_last_session(now=None):
    """The most recent session whose close has settled as of `now` (UTC or tz-aware)."""
    now = pd.Timestamp(now or dt.datetime.now(dt.timezone.utc))
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    cal = calendar()
    candidate = cal.date_to_session(now.tz_convert(MARKET_TZ).normalize().tz_localize(None), direction="previous")
    while settled_at(candidate) > now:
        candidate = cal.previous_session(candidate)
    return pd.Timestamp(candidate).tz_localize(None)


def sessions_behind(as_of, now=None):
    """How many settled sessions are missing after `as_of` (0 = up to date)."""
    expected = expected_last_session(now)
    as_of = pd.Timestamp(as_of)
    if as_of >= expected:
        return 0
    return len(sessions_between(as_of, expected)) - 1
