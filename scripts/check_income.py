"""Проверяет, что купоны/дивиденды попадают в БД. Пишет алерт в Telegram."""
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func
from database.db import Session, InvestOperationDB
from config.settings import TELEGRAM_TOKEN, ADMIN_IDS
import telebot


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('check_income')

bot = telebot.TeleBot(TELEGRAM_TOKEN)


def main():
    today = date.today()
    week_ago = today - timedelta(days=7)

    with Session() as s:
        coupons = (
            s.query(func.coalesce(func.sum(InvestOperationDB.payment_amount), 0))
            .filter(
                InvestOperationDB.kind == 'coupon',
                InvestOperationDB.date >= week_ago,
            )
            .scalar()
        ) or 0

        dividends = (
            s.query(func.coalesce(func.sum(InvestOperationDB.payment_amount), 0))
            .filter(
                InvestOperationDB.kind == 'dividend',
                InvestOperationDB.date >= week_ago,
            )
            .scalar()
        ) or 0

        last_op = (
            s.query(InvestOperationDB)
            .order_by(InvestOperationDB.date.desc())
            .first()
        )

    last_op_days = (today - last_op.date.date()).days if last_op else 999

    text = (
        f"📊 <b>Еженедельный отчёт по доходам</b>\n"
        f"\n"
        f"  • Купоны за 7 дней: <b>{float(coupons):,.2f} ₽</b>\n"
        f"  • Дивиденды за 7 дней: <b>{float(dividends):,.2f} ₽</b>\n"
        f"  • Последняя операция: <b>{last_op_days} дн. назад</b>\n"
    )

    if last_op_days > 3:
        text += (
            f"\n⚠️ <b>Внимание:</b> операции не приходят уже "
            f"{last_op_days} дней. Проверь API T-Invest."
        )

    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, text, parse_mode='HTML')
        except Exception as e:
            logger.warning("Не отправилось %s: %s", admin_id, e)

    logger.info("Отчёт отправлен")


if __name__ == '__main__':
    main()