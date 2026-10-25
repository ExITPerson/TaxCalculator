# invest/goals.py
from database.db import Session
from database.snapshot_crud import SnapshotCrud
from database.crud import BotSettingsCrud
from datetime import date

def build_goals_report(account_id: str = 'all') -> dict:
    """
    Прогресс к цели: сколько уже набрано, сколько осталось.
    Цель берется из БД (настройки бота).
    """
    with Session() as s:
        snapshots = SnapshotCrud(s).get_snapshots(account_id)
        target = BotSettingsCrud(s).get_float('target_annual_return', 15.0)

    if not snapshots:
        return {'error': 'Нет snapshots'}

    current_index = float(snapshots[-1].index_value)
    current_return = current_index - 100

    today = date.today()
    end_of_year = date(today.year, 12, 31)
    days_left = (end_of_year - today).days

    # Требуемая доходность от текущего уровня
    remaining = target - current_return

    if days_left <= 0:
        required_annual = 0.0
    else:
        required_annual = (remaining / days_left) * 365

    progress_pct = max(0, min(100, current_return / target * 100)) if target else 0

    return {
        'target_pct': target,
        'current_pct': round(current_return, 2),
        'remaining_pct': round(remaining, 2),
        'days_left': days_left,
        'required_annual_pct': round(required_annual, 2),
        'progress_pct': round(progress_pct, 1),
        'is_achievable': required_annual <= 50,  # эвристика
        'is_behind': remaining > 0 and progress_pct < 50,
    }