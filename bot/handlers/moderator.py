from bot.instance import bot_tg
from bot.decorator import require_role_cb, Role
from bot.keyboard import back_to_menu
from database.db import Session
from database.crud import CrudDB, CashWithdrawalCrud, BalanceAdjustmentCrud
from reports.report import build_detailed_report, build_quarterly_report
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
    insurance_total_net = report.get('Взносы всего (с вычетом оплаченных)', 0)

    # Детализация взносов
    fee_ip = report.get('Страховые и пенсионные за ИП', 0)
    contrib_employees = report.get('Страховые и пенсионные за сотрудников', 0)
    accident = report.get('Взносы за травматизм', 0)

    paid_taxes = report.get('Сумма оплаченных налогов', 0)
    paid_insurance = report.get('Сумма оплаченных страховых взносов', 0)

    # НДФЛ за сотрудников (он тоже обязателен к уплате)
    ndfl_salary = report.get('Налог за сотрудников', 0)

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
        "🧾 <b>Налоги(к доплате)</b>\n"
        f"  • УСН (налог):     <code>{_fmt(tax_to_pay_net)}</code>\n"
        f"    <i>из начисленного вычтено оплаченное: {_fmt(paid_taxes)}</i>\n"
        f"  • НДФЛ за сотрудников: <code>{_fmt(ndfl_salary)}</code>\n"
        "\n"
        "🏦 <b>Детализация взносов (к оплате)</b>\n"
        f"  • Пенсионные/страховые за ИП: <code>{_fmt(fee_ip)}</code>\n"
        f"  • Страховые за сотрудников:   <code>{_fmt(contrib_employees)}</code>\n"
        f"  • Взносы за травматизм:       <code>{_fmt(accident)}</code>\n"
        f"  • <b>Итого взносов:</b>       <code>{_fmt(insurance_total_net)}</code>\n"
        f"    <i>из начисленного вычтено оплаченное: {_fmt(paid_insurance)}</i>\n"

        f"  • <b>Итого к оплате (налоги и взносы):</b>       <code>{_fmt(insurance_total_net + tax_to_pay_net + ndfl_salary)}</code>\n"
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


@bot_tg.callback_query_handler(func=lambda c: c.data == 'quarterly_taxes')
@require_role_cb(Role.MODERATOR)
def cb_quarterly_taxes(call):
    bot_tg.answer_callback_query(call.id, "📅 Считаю налоги по кварталам...")

    with Session() as s:
        crud = CrudDB(s)
        quarters = build_quarterly_report(crud)

    if not quarters:
        bot_tg.send_message(call.message.chat.id, "Нет данных за текущий год.")
        return

    text = "📅 <b>Налоги и взносы по кварталам</b>\n\n"

    total_tax_to_pay = 0
    total_ins_to_pay = 0

    for q in quarters:
        text += f"<b>{q['quarter']} квартал</b>\n"
        text += f"  • Выручка: <code>{q['revenue']:,.2f} ₽</code>\n"

        # Налог УСН: исходный, после вычета, оплачено, к доплате
        text += f"  • Налог УСН: <code>{q['tax_total']:,.2f} ₽</code>\n"
        text += f"  • Налог после вычета взносов: <code>{q['tax_to_pay_gross']:,.2f} ₽</code>\n"
        text += f"  • Оплачено налога: <code>{q['tax_paid']:,.2f} ₽</code>\n"
        text += f"  • <b>К доплате налога:</b> <code>{q['tax_to_pay']:,.2f} ₽</code>\n"

        # Взносы: начислено, оплачено, к доплате
        text += f"  • Взносы начислено: <code>{q['insurance_total']:,.2f} ₽</code>\n"
        text += f"  • Оплачено взносов: <code>{q['insurance_paid']:,.2f} ₽</code>\n"
        text += f"  • <b>К доплате взносов:</b> <code>{q['insurance_to_pay']:,.2f} ₽</code>\n"

        text += f"  • <b>Итого к оплате за квартал:</b> <code>{q['total_to_pay']:,.2f} ₽</code>\n\n"

        total_tax_to_pay += q['tax_to_pay']
        total_ins_to_pay += q['insurance_to_pay']

    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🧾 <b>Всего к доплате за год:</b>\n"
    text += f"  • Налог УСН: <code>{total_tax_to_pay:,.2f} ₽</code>\n"
    text += f"  • Взносы: <code>{total_ins_to_pay:,.2f} ₽</code>\n"
    text += f"  • <b>Итого: <code>{total_tax_to_pay + total_ins_to_pay:,.2f} ₽</code></b>\n"

    text += "\n<i>* Данные по оплаченным налогам и взносам берутся из базы (операции Т-Банка).</i>"

    bot_tg.send_message(
        call.message.chat.id,
        text,
        parse_mode='HTML',
        reply_markup=back_to_menu()
    )