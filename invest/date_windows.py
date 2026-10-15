from datetime import datetime, timedelta


MAX_WINDOW_DAYS = 31


def split_period(
    date_from: str,
    date_to: str | None = None,
    max_days: int = MAX_WINDOW_DAYS,
) -> list[tuple[str, str]]:
    """
    Режет период [date_from, date_to] на окна по max_days.
    Возвращает список (from_iso, to_iso) с ISO-временем.

    date_from, date_to — 'YYYY-MM-DD'.
    """
    start = datetime.strptime(date_from, '%Y-%m-%d')
    end = (
        datetime.strptime(date_to, '%Y-%m-%d')
        if date_to
        else datetime.utcnow()
    )

    windows: list[tuple[str, str]] = []

    current = start
    while current < end:
        window_end = min(current + timedelta(days=max_days - 1), end)
        windows.append((
            current.strftime('%Y-%m-%dT00:00:00Z'),
            window_end.strftime('%Y-%m-%dT23:59:59Z'),
        ))
        current = window_end + timedelta(days=1)

    return windows