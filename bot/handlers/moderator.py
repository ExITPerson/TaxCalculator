from bot.instance import bot
from bot.decorator import require_role_cb, Role
from bot.keyboard import back_to_menu
from database.db import Session
from database.crud import CrudDB, CashWithdrawalCrud
from reports.report import build_detailed_report
from sync.operations import sync_operations


# ---------- хелперы ----------

def _fmt(value: float) -> str:
    """1234567.89 -> '1 234 567.89 ₽'"""
    return f"{value:,.2f} ₽".replace(",", " ")


def _build_report_text(report: dict) -> str:
    """Формирует HTML-текст финансового отчёта."""
    income = report.get('Поступления (выручка)', 0)
    balance_real = report.get('Реальный остаток на счету', 0)
    balance_free = report.get('Свободный остаток (после налогов и взносов)', 0)
    salary_paid = report.get('Сумма выплаченной ЗП', 0)
    limit_left = report.get('Остаток до лимита УСН', 0)
    limit_total = report.get('Лимит УСН', 0)
    tax_total = report.get('Сумма всех расходов на налоги и взносы', 0)
    tax_paid = report.get('Сумма оплаченных налогов и взносов (итого)', 0)
    cash_manual = report.get('Снятия наличных (вручную)', 0)

    return (
        "📊 <b>Финансовый отчёт</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "💵 <b>Остатки</b>\n"
        f"  • Реальный:        <code>{_fmt(balance_real)}</code>\n"
        f"  • Свободный:       <code>{_fmt(balance_free)}</code>\n"
        "  <i>после вычета налогов и взносов</i>\n"
        "\n"
        "📈 <b>Обороты</b>\n"
        f"  • Поступления:     <code>{_fmt(income)}</code>\n"
        f"  • Выплачено ЗП:    <code>{_fmt(salary_paid)}</code>\n"
        "\n"
        "💸 <b>Снятия наличных</b>\n"
        f"  • Вручную:         <code>{_fmt(cash_manual)}</code>\n"
        "\n"
        "📏 <b>Лимит УСН</b>\n"
        f"  • Лимит:           <code>{_fmt(limit_total)}</code>\n"
        f"  • Остаток:         <code>{_fmt(limit_left)}</code>\n"
        "\n"
        "🧾 <b>Налоги и взносы</b>\n"
        f"  • Оплачено всего:  <code>{_fmt(tax_paid)}</code>\n"
        f"  • К оплате:        <code>{_fmt(tax_total)}</code>\n"
        "  <i>к доплате за вычетом уже уплаченного</i>"
    )


# ---------- хендлеры ----------

@bot.callback_query_handler(func=lambda c: c.data == 'menu_report')
@require_role_cb(Role.MODERATOR)
def cb_report(call):
    bot.answer_callback_query(call.id, "🔄 Обновляю данные...")

    try:
        sync_operations()
    except Exception as e:
        bot.send_message(call.message.chat.id, f"⚠️ Ошибка синхронизации: {e}")
        return

    with Session() as session:
        cash_total = CashWithdrawalCrud(session).total()
        report = build_detailed_report(CrudDB(session), cash_withdrawn=cash_total)

    text = _build_report_text(report)

    try:
        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='HTML',
            reply_markup=back_to_menu(),
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise


@bot.callback_query_handler(func=lambda c: c.data == 'menu_balance')
@require_role_cb(Role.MODERATOR)
def cb_balance(call):
    with Session() as session:
        cash_total = CashWithdrawalCrud(session).total()
        report = build_detailed_report(CrudDB(session), cash_withdrawn=cash_total)

    balance_real = report.get('Реальный остаток на счету', 0)
    balance_free = report.get('Свободный остаток (после налогов и взносов)', 0)

    bot.edit_message_text(
        f"💰 <b>Остатки</b>\n\n"
        f"Реальный: <code>{_fmt(balance_real)}</code>\n"
        f"Свободный: <code>{_fmt(balance_free)}</code>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == 'limit')
@require_role_cb(Role.MODERATOR)
def cb_limit(call):
    with Session() as session:
        cash_total = CashWithdrawalCrud(session).total()
        report = build_detailed_report(CrudDB(session), cash_withdrawn=cash_total)

    limit_left = report.get('Остаток до лимита УСН', 0)
    limit_total = report.get('Лимит УСН', 0)
    income = report.get('Поступления (выручка)', 0)

    bot.edit_message_text(
        f"📏 <b>Лимит УСН</b>\n\n"
        f"Лимит: <code>{_fmt(limit_total)}</code>\n"
        f"Выручка: <code>{_fmt(income)}</code>\n"
        f"Остаток: <code>{_fmt(limit_left)}</code>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot.answer_callback_query(call.id)