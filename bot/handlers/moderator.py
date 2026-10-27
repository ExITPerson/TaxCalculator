from bot.instance import bot_tg
from bot.decorator import require_role_cb, Role
from bot.keyboard import back_to_menu
from database.db import Session
from database.crud import CrudDB, CashWithdrawalCrud, BalanceAdjustmentCrud
from reports.report import build_detailed_report
from sync.operations import sync_operations


# ---------- хелперы ----------

def _fmt(value: float) -> str:
    """1234567.89 -> '1 234 567.89 ₽'"""
    return f"{value:,.2f} ₽".replace(",", " ")


# bot/moderator.py

def _build_report_text(report: dict) -> str:
    income = report.get('Поступления (выручка)', 0)
    balance_real = report.get('Реальный остаток на счету', 0)
    balance_free = report.get('Свободный остаток (после налогов и взносов)', 0)
    salary_paid = report.get('Сумма выплаченной ЗП', 0)
    limit_left = report.get('Остаток до лимита УСН', 0)
    limit_total = report.get('Лимит УСН', 0)
    cash_manual = report.get('Снятия наличных (вручную)', 0)

    # --- НОВЫЕ ПЕРЕМЕННЫЕ ДЛЯ ДЕТАЛИЗАЦИИ ---
    tax_to_pay_net = report.get('Налог к оплате (с вычетом оплаченных)', 0)
    insurance_to_pay_net = report.get('Взносы всего (с вычетом оплаченных)', 0)
    paid_taxes = report.get('Сумма оплаченных налогов', 0)
    paid_insurance = report.get('Сумма оплаченных страховых взносов', 0)

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
        "🧾 <b>Налоги и взносы (к доплате)</b>\n"
        f"  • УСН (налог):     <code>{_fmt(tax_to_pay_net)}</code>\n"
        f"    <i>из начисленного вычтено оплаченное: {_fmt(paid_taxes)}</i>\n"
        f"  • Взносы (всего):  <code>{_fmt(insurance_to_pay_net)}</code>\n"
        f"    <i>из начисленного вычтено оплаченное: {_fmt(paid_insurance)}</i>\n"
    )


# ---------- отчёт ----------

@bot_tg.callback_query_handler(func=lambda c: c.data == 'menu_report')
@require_role_cb(Role.MODERATOR)
def cb_report(call):
    bot_tg.answer_callback_query(call.id, "🔄 Обновляю данные...")

    try:
        sync_operations()
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка синхронизации: {e}")
        return

    with Session() as session:
        cash_total = CashWithdrawalCrud(session).total()
        adj_total = BalanceAdjustmentCrud(session).total()
        report = build_detailed_report(
            CrudDB(session),
            cash_withdrawn=cash_total,
            balance_adjustment=adj_total,
        )

    text = _build_report_text(report)

    try:
        bot_tg.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='HTML',
            reply_markup=back_to_menu(),
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise


@bot_tg.callback_query_handler(func=lambda c: c.data == 'menu_balance')
@require_role_cb(Role.MODERATOR)
def cb_balance(call):
    with Session() as session:
        cash_total = CashWithdrawalCrud(session).total()
        adj_total = BalanceAdjustmentCrud(session).total()
        report = build_detailed_report(
            CrudDB(session),
            cash_withdrawn=cash_total,
            balance_adjustment=adj_total,
        )

    balance_real = report.get('Реальный остаток на счету', 0)
    balance_free = report.get('Свободный остаток (после налогов и взносов)', 0)

    text = (
        f"💰 <b>Остатки</b>\n\n"
        f"Реальный: <code>{_fmt(balance_real)}</code>\n"
        f"Свободный: <code>{_fmt(balance_free)}</code>"
    )

    bot_tg.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot_tg.answer_callback_query(call.id)


@bot_tg.callback_query_handler(func=lambda c: c.data == 'limit')
@require_role_cb(Role.MODERATOR)
def cb_limit(call):
    with Session() as session:
        cash_total = CashWithdrawalCrud(session).total()
        adj_total = BalanceAdjustmentCrud(session).total()
        report = build_detailed_report(
            CrudDB(session),
            cash_withdrawn=cash_total,
            balance_adjustment=adj_total,
        )

    limit_left = report.get('Остаток до лимита УСН', 0)
    limit_total = report.get('Лимит УСН', 0)
    income = report.get('Поступления (выручка)', 0)

    bot_tg.edit_message_text(
        f"📏 <b>Лимит УСН</b>\n\n"
        f"Лимит: <code>{_fmt(limit_total)}</code>\n"
        f"Выручка: <code>{_fmt(income)}</code>\n"
        f"Остаток: <code>{_fmt(limit_left)}</code>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot_tg.answer_callback_query(call.id)