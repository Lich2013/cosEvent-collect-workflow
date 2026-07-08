import datetime


BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))


def beijing_now() -> datetime.datetime:
    """Return the current Beijing time; tests can monkeypatch this function."""
    return datetime.datetime.now(BEIJING_TZ)


def beijing_today() -> datetime.date:
    return beijing_now().date()


def beijing_today_str() -> str:
    return beijing_today().strftime("%Y-%m-%d")


def beijing_now_str() -> str:
    return beijing_now().strftime("%Y-%m-%d %H:%M:%S")
