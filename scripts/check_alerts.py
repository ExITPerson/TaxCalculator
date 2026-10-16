"""Проверяет портфель и шлёт алерты при значимых событиях."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import Session
from database.snapshot_crud import SnapshotCrud
from config.settings import TELEGRAM_TOKEN, ADMIN_IDS
import telebot


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('check_alerts')

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Пороги
ALERT_DROP_PCT = 3.0
ALERT_GROWTH_PCT = 3.0
ALERT_PNL_NEGATIVE = -10000
ALERT_PNL_POSITIVE = 10000


def main():
    with Session() as s:
        snapshots = SnapshotCrud(s).get_snapshots('all')

    if len(snapshots) < 2:
        logger.info("Мало снапшотов — пропускаем")
        return

    last = snapshots[-1]
    prev = snapshots[-2]

    last_value = float(last.total_value)
    prev_value = float(prev.total_value)
    last_pnl = float(last.pnl_value or 0)

    if prev_value == 0:
        logger.info("Предыдущий снапшот = 0 — пропускаем")
        return

    daily_pct = (last_value / prev_value - 1) * 100

    alerts = []

    if daily_pct <= -ALERT_DROP_PCT:
        alerts.append(
            f"🔴 <b>Просадка портфеля</b>\n"
            f"  • За день: <code>{daily_pct:+.2f}%</code>\n"
            f"  • Стоимость: <code>{last_value:,.2f} ₽</code>"
        )

    if daily_pct >= ALERT_GROWTH_PCT:
        alerts.append(
            f"🟢 <b>Рост портфеля</b>\n"
            f"  • За день: <code>{daily_pct:+.2f}%</code>\n"
            f"  • Стоимость: <code>{last_value:,.2f} ₽</code>"
        )

    if last_pnl <= ALERT_PNL_NEGATIVE:
        alerts.append(
            f"⚠️ <b>P&L ниже {ALERT_PNL_NEGATIVE:,.0f} ₽</b>\n"
            f"  • Текущий P&L: <code>{last_pnl:,.2f} ₽</code>"
        )

    if last_pnl >= ALERT_PNL_POSITIVE:
        alerts.append(
            f"🎉 <b>P&L выше {ALERT_PNL_POSITIVE:,.0f} ₽</b>\n"
            f"  • Текущий P&L: <code>{last_pnl:,.2f} ₽</code>"
        )

    if not alerts:
        logger.info("Нет событий для алерта")
        return

    for alert in alerts:
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, alert, parse_mode='HTML')
            except Exception as e:
                logger.warning("Не отправилось %s: %s", admin_id, e)


if __name__ == '__main__':
    main()