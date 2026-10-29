from database.crud import CrudDB
from taxes.calculator import Taxes


KNOWN_INNS = {
    '7710140679':   'Т-Банк (комиссии)',
    '7727406020':   'ФНС (налоги)',
    '7704270863':   'ФССП (взыскания)',
    '7703363868':   'СФР (взносы)',
    '771617552180': 'ИП (я сам)',
    '7724892407':   'ООО «ПСК ГК ГОРОД»',
    '7727312358':   'ООО «СКБИ ВАРЯГ»',
}

# Категория → какие поля из get_sums_by_category суммировать
INCOME_CATEGORIES = {
    'Поступление':          ('income',),
    'Доход от депозита':    ('internal',),
    'Пополнение с карты':   ('internal',),
    'Оплата по карте':      ('income',),
}

EXPENSE_CATEGORIES = {
    'Расход':                        ('expense',),
    'Выплата ЗП':                    ('expense',),
    'Налоговые платежи':             ('expense',),
    'Страховые взносы':              ('expense',),
    'Взыскание ФССП':                ('expense',),
    'Снятие наличных':               ('expense',),
    'Перевод с карты':               ('expense',),
    'Оплата по карте':               ('expense',),
    'Перевод собственных средств':   ('expense', 'internal'),
    'Комиссия банка':                ('expense',),
    'Комиссия за выплату ЗП':        ('expense',),
}

IGNORE_CATEGORIES = {
    'Перевод на депозит',
    'Возврат с депозита',
    'Внутренний перевод',
}


def build_detailed_report(
        crud: CrudDB,
        cash_withdrawn: float = 0.0,
        balance_adjustment: float = 0.0,
) -> dict:
    """
    :param cash_withdrawn: ручные снятия наличных — ТОЛЬКО для отчётности,
                           НЕ влияет на расчёт остатка
    :param balance_adjustment: ручная корректировка остатка (может быть ±)
    """
    summ_categories = crud.get_sums_by_category()
    by_cat = {c['category']: c for c in summ_categories}

    def get_income(name): return float(by_cat.get(name, {}).get('income', 0.0))
    def get_expense(name): return float(by_cat.get(name, {}).get('expense', 0.0))
    def get_internal(name): return float(by_cat.get(name, {}).get('internal', 0.0))

    # Налоговая база (УСН «Доходы» 6%)
    revenue = get_income('Поступление')
    salary = get_expense('Выплата ЗП')
    revenue_overnight = get_internal('Доход от депозита')

    paid_taxes = get_expense('Налоговые платежи')
    paid_insurance = get_expense('Страховые взносы')
    paid_salary = get_expense('Выплата ЗП')

    # Реальный остаток
    actual_income = 0.0
    actual_expenses = 0.0

    for c in summ_categories:
        cat = c['category']
        if cat in IGNORE_CATEGORIES:
            continue

        if cat in INCOME_CATEGORIES:
            for field in INCOME_CATEGORIES[cat]:
                actual_income += c[field]

        if cat in EXPENSE_CATEGORIES:
            for field in EXPENSE_CATEGORIES[cat]:
                actual_expenses += c[field]

    # ВАЖНО: cash_withdrawn — это НЕ расход из API, а ручная отчётная цифра.
    # Она уже включена в 'Снятие наличных' из API (если такие операции там есть).
    # Отдельная ручная запись идёт только в отчётное поле, остаток не трогает.
    real_balance = actual_income - actual_expenses + balance_adjustment

    report = Taxes().get_detailed_report(
        revenue=revenue,
        salary=salary,
        revenue_overnight=revenue_overnight,
        actual_income=actual_income,
        actual_expenses=actual_expenses,
        paid_taxes=paid_taxes,
        paid_insurance=paid_insurance,
        paid_salary=paid_salary,
        internal_income=revenue_overnight,
    )

    # Подменяем реальный остаток с учётом корректировки
    report['Реальный остаток на счету'] = round(real_balance, 2)

    # Пересчитываем свободный остаток от скорректированного
    tax_net = report.get('Налог к оплате (с вычетом оплаченных)', 0)
    ins_net = report.get('Взносы всего (с вычетом оплаченных)', 0)
    ndfl = report.get('Налог за сотрудников', 0)
    report['Свободный остаток (после налогов и взносов)'] = round(
        real_balance - tax_net - ins_net - ndfl, 2
    )

    # Отчётные поля — НЕ влияют на остаток
    report['Снятия наличных (вручную)'] = round(cash_withdrawn, 2)
    report['Корректировка остатка'] = round(balance_adjustment, 2)

    return report


def counterparty_detailed_report(crud: CrudDB) -> list[dict]:
    rows = crud.get_sums_by_counterparty_or_category()

    agg: dict[tuple, dict] = {}

    for r in rows:
        category = r['category']
        if category in IGNORE_CATEGORIES:
            continue

        name, inn = r['name'], r['inn']

        if name.startswith('— '):
            key = ('Прочие (без контрагента)', '')
            display_name = 'Прочие (без контрагента)'
        else:
            display_name = KNOWN_INNS.get(inn) or name or inn or 'Без имени'
            key = (display_name, inn)

        if key not in agg:
            agg[key] = {'name': display_name, 'inn': inn,
                        'income': 0.0, 'expense': 0.0, 'internal': 0.0}

        direction = r['direction']
        total = r['total']

        if direction == 'IN':
            agg[key]['income'] += total
        elif direction == 'OUT':
            agg[key]['expense'] += total
        elif direction == 'INTERNAL':
            if category == 'Перевод собственных средств':
                agg[key]['expense'] += total
            elif category == 'Доход от депозита':
                agg[key]['income'] += total
            else:
                agg[key]['internal'] += total

    result = []
    for item in agg.values():
        if item['income'] == 0 and item['expense'] == 0 and item['internal'] == 0:
            continue
        item['total'] = item['income'] + item['expense'] + item['internal']
        item['net'] = item['income'] - item['expense']
        result.append(item)

    return sorted(result, key=lambda x: x['total'], reverse=True)


# reports/report.py (добавьте в конец файла)

def build_quarterly_report(crud: CrudDB, year: int = None) -> list[dict]:
    """
    Считает налоги и взносы по кварталам за указанный год (по умолчанию — текущий).
    Фиксированная часть взносов (57 390 ₽) делится на 4 квартала.
    1% с превышения (300 000 ₽) распределяется пропорционально выручке квартала.
    Налог УСН уменьшается на взносы (с учетом ограничения 50%).
    """
    from datetime import date
    from sqlalchemy import func, extract
    from database.db import OperationsDB
    from taxes.calculator import Taxes

    if year is None:
        year = date.today().year

    session = crud._CrudDB__session

    # 1. Выручка по месяцам
    revenue_by_month = (
        session.query(
            extract('month', OperationsDB.date).label('month'),
            func.coalesce(func.sum(OperationsDB.amount), 0)
        )
        .filter(
            OperationsDB.category == 'Поступление',
            OperationsDB.direction == 'IN',
            extract('year', OperationsDB.date) == year,
        )
        .group_by(extract('month', OperationsDB.date))
        .all()
    )

    # 2. Оплаченные налоги по месяцам
    taxes_by_month = (
        session.query(
            extract('month', OperationsDB.date).label('month'),
            func.coalesce(func.sum(OperationsDB.amount), 0)
        )
        .filter(
            OperationsDB.category == 'Налоговые платежи',
            extract('year', OperationsDB.date) == year,
        )
        .group_by(extract('month', OperationsDB.date))
        .all()
    )

    # 3. Оплаченные взносы по месяцам
    insurance_by_month = (
        session.query(
            extract('month', OperationsDB.date).label('month'),
            func.coalesce(func.sum(OperationsDB.amount), 0)
        )
        .filter(
            OperationsDB.category == 'Страховые взносы',
            extract('year', OperationsDB.date) == year,
        )
        .group_by(extract('month', OperationsDB.date))
        .all()
    )

    rev = {int(m): float(a) for m, a in revenue_by_month}
    tax_paid = {int(m): float(a) for m, a in taxes_by_month}
    ins_paid = {int(m): float(a) for m, a in insurance_by_month}

    taxes_calc = Taxes()

    quarters = []
    total_revenue_year = sum(rev.values())
    fixed_quarter = taxes_calc.FIXED_FEE / 4
    excess_revenue = max(0, total_revenue_year - taxes_calc.DUE_THRESHOLD)
    excess_fee_year = excess_revenue * taxes_calc.DUE_RATE

    for q, months in enumerate([(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)], 1):
        q_rev = sum(rev.get(m, 0) for m in months)
        q_tax_paid = sum(tax_paid.get(m, 0) for m in months)
        q_ins_paid = sum(ins_paid.get(m, 0) for m in months)

        # Налог УСН: 6% от выручки квартала
        tax_total = taxes_calc._get_tax(q_rev)

        # Взносы за квартал = фикс/4 + доля 1% (пропорционально выручке квартала)
        share = (q_rev / total_revenue_year) if total_revenue_year > 0 else 0
        excess_fee_q = excess_fee_year * share
        ins_total = fixed_quarter + excess_fee_q

        # --- УМЕНЬШЕНИЕ НАЛОГА НА ВЗНОСЫ (как в get_full_report) ---
        tax_after_deduction = tax_total - ins_total
        min_tax = tax_total * taxes_calc.MAX_DEDUCTION_SHARE
        tax_to_pay_gross = round(max(min_tax, tax_after_deduction), 2)

        # К доплате (за вычетом оплаченного)
        tax_to_pay = max(0.0, tax_to_pay_gross - q_tax_paid)
        ins_to_pay = max(0.0, ins_total - q_ins_paid)

        quarters.append({
            'quarter': q,
            'revenue': round(q_rev, 2),
            'tax_total': round(tax_total, 2),
            'tax_to_pay_gross': round(tax_to_pay_gross, 2),
            'tax_paid': round(q_tax_paid, 2),
            'tax_to_pay': round(tax_to_pay, 2),
            'insurance_total': round(ins_total, 2),
            'insurance_paid': round(q_ins_paid, 2),
            'insurance_to_pay': round(ins_to_pay, 2),
            'total_to_pay': round(tax_to_pay + ins_to_pay, 2),
        })

    return quarters