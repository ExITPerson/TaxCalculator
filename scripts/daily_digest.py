# scripts/daily_digest.py
import sys
import logging
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import TELEGRAM_TOKEN, ADMIN_IDS
import telebot
from database.db import Session
from database.snapshot_crud import SnapshotCrud
from database.crud import InvestCrud
from reports.index_report import build_index_chart
from invest.backfill import backfill_incremental

logger = logging.getLogger('daily_digest')
bot = telebot.TeleBot(TELEGRAM_TOKEN)


def send_digest():
    logger.info("=== Подготовка утреннего дайджеста ===")

    # 1. Обновляем данные перед отправкой
    try:
        backfill_incremental()
    except Exception as e:
        logger.error(f"Ошибка backfill: {e}")

    # 2. Собираем цифры
    with Session() as s:
        snapshots = SnapshotCrud(s).get_snapshots('all')
        if len(snapshots) < 2:
            logger.warning("Мало снапшотов для дайджеста")
            return

        last = snapshots[-1]
        prev = snapshots[-2]

        total = float(last.total_value)
        pnl = float(last.pnl_value or 0)

        # Считаем вложенные деньги (net_invested)
        crud = InvestCrud(s)
        deposits = crud.total_deposits()
        withdrawals = crud.total_withdrawals()
        net_invested = deposits - withdrawals

        # Процент P&L
        pnl_pct = (pnl / net_invested * 100) if net_invested > 0 else 0

        # Дневное изменение
        daily_change = total - float(prev.total_value)
        daily_pct = (daily_change / float(prev.total_value) * 100) if float(prev.total_value) > 0 else 0

    # 3. Формируем текст
    emoji = "🟢" if pnl >= 0 else "🔴"
    text = (
        f"☀️ <b>Доброе утро! Дайджест портфеля</b>\n\n"
        f"💼 Стоимость: <code>{total:,.2f} ₽</code>\n"
        f"💵 Внесено (net): <code>{net_invested:,.2f} ₽</code>\n"
        f"{emoji} P&L: <code>{pnl:+,.2f} ₽</code> (<code>{pnl_pct:+.2f}%</code> от вложений)\n"
        f"📊 За день: <code>{daily_change:+,.2f} ₽</code> (<code>{daily_pct:+.2f}%</code>)\n\n"
        f"<i>Хорошего дня и зеленых свечей!</i>"
    )

    # 4. Строим график
    try:
        chart_path = build_index_chart()
        with open(chart_path, 'rb') as f:
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_photo(admin_id, f, caption=text, parse_mode='HTML')
                except Exception as e:
                    logger.warning(f"Не удалось отправить фото админу {admin_id}: {e}")
                    bot.send_message(admin_id, text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка построения графика: {e}")
        # Если график не построился, шлем хотя бы текст
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text, parse_mode='HTML')
            except:
                pass

    logger.info("=== Дайджест отправлен ===")