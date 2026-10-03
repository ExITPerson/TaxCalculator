from database.crud import CrudDB
from taxes.calculator import Taxes


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
}

# Категории, которые уводят деньги со счёта, но с direction="INTERNAL"
# (вывод на свою карту — для расчётного счёта это расход)
INTERNAL_OUT_CATEGORIES = {
    'Внутренний перевод',
}

# Категории прихода с direction="IN"
INCOME_CATEGORIES = {
    'Поступление',
    'Оплата по карте',       # возвраты/отмены
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


def build_detailed_report(crud: CrudDB) -> dict:
    summ_categories = crud.get_sums_by_category()
    by_cat: dict[str, dict] = {c['category']: c for c in summ_categories}

    def get_income(name: str) -> float:
        return float(by_cat.get(name, {}).get('income', 0.0))

    def get_expense(name: str) -> float:
        return float(by_cat.get(name, {}).get('expense', 0.0))

    def get_internal(name: str) -> float:
        return float(by_cat.get(name, {}).get('internal', 0.0))

    # --- База для налога ---
    revenue = get_income('Поступление')
    salary = get_expense('Выплата ЗП')
    revenue_overnight = get_internal('Доход от депозита')

    # --- Оплаченное ---
    paid_taxes = get_expense('Налоговые платежи')
    paid_insurance = get_expense('Страховые взносы')
    paid_salary = get_expense('Выплата ЗП')

    # --- Реальные приходы ---
    actual_income = sum(get_income(cat) for cat in INCOME_CATEGORIES)
    actual_income += sum(get_internal(cat) for cat in INTERNAL_IN_CATEGORIES)

    # --- Реальные расходы ---
    actual_expenses = sum(get_expense(cat) for cat in EXPENSE_CATEGORIES)
    actual_expenses += sum(get_internal(cat) for cat in INTERNAL_OUT_CATEGORIES)

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