from database.crud import CrudDB
from taxes.calculator import Taxes


KNOWN_INNS = {
    '7710140679':   'Т-Банк (комиссии)',
    '7727406020':   'ФНС (налоги)',
    '7704270863':   'ФССП (взыскания)',
    '7703363868':   'СФР (взносы)',
    '771617552180': 'ИП (я сам)',         # твой ИНН — проценты с овернайта
    # остальные можно не маппить, будет показываться ИНН
}

# Категории, которые уводят деньги со счёта (expense)
EXPENSE_CATEGORIES = {
    'Расход',
    'Снятие наличных',
    'Перевод с карты',
    'Оплата по карте',
    'Выплата ЗП',
    'Комиссия банка',
    'Комиссия за выплату ЗП',
    'Взыскание ФССП',
    'Налоговые платежи',
    'Страховые взносы',
    'Внутренний перевод',       # теперь он в expense
}

# Категории, которые уводят деньги со счёта, но с direction="INTERNAL"
# (вывод на свою карту — для расчётного счёта это расход)
INTERNAL_OUT_CATEGORIES = {
    'Внутренний перевод',
}

# Категории прихода с direction="IN"
INCOME_CATEGORIES = {
    'Поступление',
    'Оплата по карте',          # возвраты
    'Доход от депозита',        # теперь он в income
}

# Категории прихода с direction="INTERNAL"
INTERNAL_IN_CATEGORIES = {
    'Доход от депозита',     # проценты по овернайту
}

# Категории, которые не влияют на остаток (деньги вернутся)
# — Перевод на депозит и Возврат с депозита игнорируем, т.к. это обороты
SKIP_CATEGORIES = {
    'Перевод на депозит',
    'Возврат с депозита',
}
# Категории, которые считаем расходом, даже если direction == "INTERNAL"
INTERNAL_AS_EXPENSE = {'Внутренний перевод'}

# Категории, которые считаем приходом при direction == "INTERNAL"
INTERNAL_AS_INCOME = {'Доход от депозита'}

# Полностью игнорируем — это обороты, не влияющие на остаток
IGNORE_CATEGORIES = {'Перевод на депозит', 'Возврат с депозита'}



def build_detailed_report(crud: CrudDB) -> dict:
    summ_categories = crud.get_sums_by_category()
    by_cat: dict[str, dict] = {c['category']: c for c in summ_categories}

    def get_income(name: str) -> float:
        return float(by_cat.get(name, {}).get('income', 0.0))

    def get_expense(name: str) -> float:
        return float(by_cat.get(name, {}).get('expense', 0.0))

    # --- База для налога ---
    revenue = get_income('Поступление')
    salary = get_expense('Выплата ЗП')
    revenue_overnight = get_income('Доход от депозита')

    # --- Оплаченное ---
    paid_taxes = get_expense('Налоговые платежи')
    paid_insurance = get_expense('Страховые взносы')
    paid_salary = get_expense('Выплата ЗП')

    # --- Реальные приходы / расходы ---
    actual_income = sum(get_income(cat) for cat in INCOME_CATEGORIES)
    actual_expenses = sum(get_expense(cat) for cat in EXPENSE_CATEGORIES)

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

    return report

def counterparty_detailed_report(crud: CrudDB) -> list[dict]:
    rows = crud.get_sums_by_counterparty_or_category()

    agg: dict[tuple, dict] = {}

    for r in rows:
        category = r['category']
        if category in IGNORE_CATEGORIES:
            continue

        name, inn = r['name'], r['inn']

        # FIX: все «без контрагента» объединяем под одним ключом
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
            if category in INTERNAL_AS_EXPENSE:
                agg[key]['expense'] += total
            elif category in INTERNAL_AS_INCOME:
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