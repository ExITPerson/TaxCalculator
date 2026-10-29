# test_quarters.py
from database.db import Session
from database.crud import CrudDB
from reports.report import build_quarterly_report

with Session() as s:
    crud = CrudDB(s)
    quarters = build_quarterly_report(crud)

if not quarters:
    print("Нет данных за текущий год.")
else:
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

    # Выводим текст в консоль (как он будет выглядеть в Telegram)
    print("\n=== ТЕКСТ ДЛЯ БОТА ===\n")
    print(text)