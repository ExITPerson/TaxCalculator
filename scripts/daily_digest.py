# scripts/daily_digest.py
import sys
import logging
from pathlib import Path
from datetime import date, timedelta
from sqlalchemy import func

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import TELEGRAM_TOKEN, ADMIN_IDS, ACCOUNTS_ID
import telebot
from database.db import Session, InvestOperationDB
from database.crud import InvestCrud, BotSettingsCrud
from database.snapshot_crud import SnapshotCrud
from reports.index_report import build_index_chart
from invest.backfill import backfill_incremental
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio
from invest.goals import build_goals_report
from invest.metrics import rolling_volatility  # Для светофора

logger = logging.getLogger('daily_digest')
bot = telebot.TeleBot(TELEGRAM_TOKEN)


def get_upcoming_events(days_ahead: int = 1) -> list:
    """Ищет купоны/дивиденды на сегодня и ближайшие дни."""
    today = date.today()
    end_date = today + timedelta(days=days_ahead)

    with Session() as s:
        ops = s.query(InvestOperationDB).filter(
            InvestOperationDB.kind.in_(['coupon', 'dividend', 'amortization', 'bond_repayment']),
            InvestOperationDB.date >= today,
            InvestOperationDB.date <= end_date
        ).order_by(InvestOperationDB.date).all()

        return [{
            'kind': op.kind,
            'amount': float(op.payment_amount),
            'ticker': op.ticker or '—',
            'date': op.date.date()
        } for op in ops]


def get_portfolio_performance(days: int) -> float | None:
    """Считает доходность портфеля (TWR) за N дней."""
    with Session() as s:
        snapshots = SnapshotCrud(s).get_snapshots('all')
        if len(snapshots) < 2:
            return None

        target_date = date.today() - timedelta(days=days)

        start_snapshot = None
        for snap in snapshots:
            if snap.date.date() >= target_date:
                start_snapshot = snap
                break

        if not start_snapshot:
            return None

        end_snapshot = snapshots[-1]
        start_idx = float(start_snapshot.index_value)
        end_idx = float(end_snapshot.index_value)

        if start_idx <= 0:
            return None

        return (end_idx / start_idx - 1) * 100


def get_imoex_performance(days: int) -> float | None:
    """Считает доходность IMOEX за N дней."""
    try:
        IMOEX_FIGI = 'BBG00KDWPPW2'
        today = date.today()
        start_date = today - timedelta(days=days)

        with Session() as s:
            crud = SnapshotCrud(s)
            cached = crud.get_cached_candles(IMOEX_FIGI, start_date, today)

            if len(cached) < 2:
                return None

            sorted_days = sorted(cached.keys())
            start_p = cached[sorted_days[0]]
            end_p = cached[sorted_days[-1]]

            if start_p <= 0:
                return None

            return (end_p / start_p - 1) * 100
    except Exception as e:
        logger.error(f"Ошибка получения IMOEX за {days} дней: {e}")
        return None


def get_risk_light() -> str:
    """Возвращает строку-светофор на основе волатильности."""
    try:
        with Session() as s:
            snapshots = SnapshotCrud(s).get_snapshots('all')
            if len(snapshots) < 30:
                return "⚪ <i>Мало данных для оценки риска</i>"

            # Берем индекс TWR за последние 30 дней
            values = [float(s.index_value) for s in snapshots if s.index_value > 0]
            if len(values) < 30:
                return "⚪ <i>Мало данных для оценки риска</i>"

            # Считаем волатильность
            vol_series = rolling_volatility(values, window=30)
            vol = vol_series[-1]

            if vol is None:
                return "⚪ <i>Мало данных для оценки риска</i>"

            if vol < 10:
                return f"🟢 <b>Низкий риск</b> (волатильность {vol:.1f}%)"
            elif vol < 20:
                return f"🟡 <b>Средний риск</b> (волатильность {vol:.1f}%)"
            else:
                return f"🔴 <b>Высокий риск</b> (волатильность {vol:.1f}%)"
    except Exception as e:
        logger.error(f"Ошибка оценки риска: {e}")
        return "⚪ <i>Ошибка оценки риска</i>"


def send_digest():
    logger.info("=== Подготовка утреннего дайджеста ===")

    # 1. Обновляем данные
    try:
        backfill_incremental()
    except Exception as e:
        logger.error(f"Ошибка backfill: {e}")

    # 2. Получаем РЕАЛЬНУЮ стоимость портфеля из API
    total_value = 0.0
    free_cash = 0.0
    positions = []
    try:
        with TInvestPortfolioClient() as client:
            for acc in ACCOUNTS_ID:
                raw = client.fetch_portfolio(acc)
                if raw:
                    p = parse_portfolio(raw)
                    total_value += p.get('total_amount_portfolio', 0.0)
                    free_cash += p.get('total_amount_currencies', 0.0)
                    for pos in p['positions']:
                        if pos['quantity'] > 0:
                            positions.append({
                                'ticker': pos.get('ticker') or pos['figi'][:6],
                                'pnl': pos.get('expected_yield', 0)
                            })
    except Exception as e:
        logger.error(f"Ошибка получения портфеля из API: {e}")

    # 3. Собираем остальные цифры из БД
    with Session() as s:
        snapshots = SnapshotCrud(s).get_snapshots('all')
        if not snapshots:
            logger.warning("Мало снапшотов для дайджеста")
            return

        last = snapshots[-1]
        prev = snapshots[-2] if len(snapshots) >= 2 else last

        crud = InvestCrud(s)
        deposits = crud.total_deposits()
        withdrawals = crud.total_withdrawals()
        net_invested = deposits - withdrawals

        if total_value <= 0:
            total_value = float(last.total_value)
            logger.warning("API не вернул стоимость. Берем из последнего снапшота: %.2f", total_value)

        # Считаем P&L НАПРЯМУЮ
        pnl = total_value - net_invested
        pnl_pct = (pnl / net_invested * 100) if net_invested > 0 else 0

        # Дневное изменение
        prev_value = float(prev.total_value)
        daily_change = total_value - prev_value
        daily_pct = (daily_change / prev_value * 100) if prev_value > 0 else 0

    # 4. Лидер / Аутсайдер дня
    top_gainer = "—"
    top_loser = "—"
    if positions:
        positions.sort(key=lambda x: x['pnl'], reverse=True)
        top_gainer = f"{positions[0]['ticker']} ({positions[0]['pnl']:+.0f} ₽)"
        top_loser = f"{positions[-1]['ticker']} ({positions[-1]['pnl']:+.0f} ₽)"

    # 5. События на день
    events = get_upcoming_events(days_ahead=1)
    events_text = ""
    if events:
        events_text = "\n📅 <b>События сегодня:</b>\n"
        for ev in events:
            kind_ru = {'coupon': 'Купон', 'dividend': 'Дивиденд', 'amortization': 'Амортизация',
                       'bond_repayment': 'Погашение'}.get(ev['kind'], ev['kind'])
            events_text += f"  • <b>{ev['ticker']}</b>: {kind_ru} <code>{ev['amount']:,.0f} ₽</code>\n"

    # 6. Динамика (неделя и месяц)
    week_portfolio = get_portfolio_performance(7)
    month_portfolio = get_portfolio_performance(30)
    week_imoex = get_imoex_performance(7)
    month_imoex = get_imoex_performance(30)

    dynamics_text = ""
    if any([week_portfolio is not None, month_portfolio is not None]):
        dynamics_text += "\n📊 <b>Динамика</b>\n"

        if week_portfolio is not None:
            dynamics_text += f"  📈 Портфель (нед): <code>{week_portfolio:+.2f}%</code>\n"
        if week_imoex is not None:
            dynamics_text += f"  🌍 IMOEX (нед): <code>{week_imoex:+.2f}%</code>\n"

        if month_portfolio is not None:
            dynamics_text += f"  📈 Портфель (мес): <code>{month_portfolio:+.2f}%</code>\n"
        if month_imoex is not None:
            dynamics_text += f"  🗓 IMOEX (мес): <code>{month_imoex:+.2f}%</code>\n"

    # 7. Светофор риска
    risk_text = get_risk_light()

    # 8. Прогресс к цели
    goals_text = ""
    try:
        goals = build_goals_report()
        if 'error' not in goals:
            goals_text = (
                f"\n🎯 <b>Цель на год:</b> <code>{goals['target_pct']:.1f}%</code>\n"
                f"  Сейчас: <code>{goals['current_pct']:+.2f}%</code> (выполнено {goals['progress_pct']:.0f}%)\n"
            )
    except Exception as e:
        logger.error(f"Ошибка целей: {e}")

    # 9. Формируем текст
    emoji = "🟢" if pnl >= 0 else "🔴"
    text = (
        f"☀️ <b>Доброе утро! Дайджест портфеля</b>\n\n"
        f"💼 Стоимость: <code>{total_value:,.2f} ₽</code>\n"
        f"💵 Свободный кэш: <code>{free_cash:,.2f} ₽</code>\n"
        f"💵 Внесено (net): <code>{net_invested:,.2f} ₽</code>\n"
        f"{emoji} P&L: <code>{pnl:+,.2f} ₽</code> (<code>{pnl_pct:+.2f}%</code>)\n"
        f"📊 За день: <code>{daily_change:+,.2f} ₽</code> (<code>{daily_pct:+.2f}%</code>)\n"
        f"\n🚦 <b>Риск:</b> {risk_text}\n"
        f"{dynamics_text}"
        f"{goals_text}"
    )

    if top_gainer != "—":
        text += f"\n🏆 Лидер: <b>{top_gainer}</b>\n"
        text += f"🚨 Аутсайдер: <b>{top_loser}</b>\n"

    text += events_text

    text += f"\n<i>Хорошего дня и зеленых свечей!</i>"

    # 10. Отправка двух графиков
    try:
        # --- График 1: Основной TWR ---
        chart_path = build_index_chart()
        with open(chart_path, 'rb') as f:
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_photo(admin_id, f, caption=text, parse_mode='HTML')
                except Exception as e:
                    logger.warning(f"Не удалось отправить фото админу {admin_id}: {e}")
                    bot.send_message(admin_id, text, parse_mode='HTML')

        # --- График 2: Тепловая карта (P&L) ---
        try:
            from reports.portfolio_charts import build_pnl_treemap
            treemap_path = build_pnl_treemap()
            with open(treemap_path, 'rb') as f2:
                for admin_id in ADMIN_IDS:
                    try:
                        bot.send_photo(admin_id, f2,
                                       caption="🔥 <b>Тепловая карта P&L</b>\nРазмер = стоимость, Цвет = доходность",
                                       parse_mode='HTML')
                    except Exception as e:
                        logger.warning(f"Не удалось отправить тепловую карту админу {admin_id}: {e}")
        except Exception as e:
            logger.error(f"Ошибка построения тепловой карты: {e}")

    except Exception as e:
        logger.error(f"Ошибка построения основного графика: {e}")
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text, parse_mode='HTML')
            except:
                pass

    logger.info("=== Дайджест отправлен ===")