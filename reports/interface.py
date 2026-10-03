import logging

from database.db import Session

def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    logging.getLogger("urllib3").setLevel(logging.ERROR)

def print_detailed_report(report: dict) -> None:
    print()
    print("=" * 68)
    print("  ФИНАНСОВЫЙ ОТЧЁТ (УСН «Доходы», 6%)")
    print("=" * 68)

    sections = [
        ("💵 ОСТАТКИ", [
            'Реальный остаток на счету',
            'Свободный остаток (после налогов и взносов)',
        ]),
        ("📈 ОБОРОТЫ", [
            'Поступления (выручка)',
            'Выплаченная ЗП',
            'Расходы',
        ]),
        ("📏 ЛИМИТ УСН", [
            'Лимит УСН',
            'Остаток до лимита УСН',
        ]),
        ("📊 НАЛОГИ", [
            'Налог за поступления',
            'Налог за сотрудников',
            'Налог к оплате (общий)',
            'Налог к оплате (с вычетом оплаченных)',
        ]),
        ("🏦 ВЗНОСЫ", [
            'Страховые и пенсионные за ИП',
            'Страховые и пенсионные за сотрудников',
            'Взносы за травматизм',
            'Взносы всего (с вычетом оплаченных)',
        ]),
        ("💰 УПЛАЧЕНО ИТОГО", [
            'Сумма оплаченных налогов',
            'Сумма оплаченных страховых взносов',
            'Сумма оплаченных налогов и взносов (итого)',
        ]),
        ("📉 ИТОГИ РАСХОДОВ", [
            'Сумма всех расходов на налоги и взносы',
            'Сумма расходов общая',
        ]),
        ("🌙 ОВЕРНАЙТ", [
            'Сумма заработанная с овернайта',
            'Налог на овернайт',
        ]),
    ]

    for title, keys in sections:
        print(f"\n  {title}")
        print("  " + "-" * 64)
        for key in keys:
            value = report.get(key, 0.0)
            print(f"    {key:<44} {value:>15,.2f} ₽")

    print()
    print("=" * 68)

def _fmt_money(value: float) -> str:
    """Форматирует сумму в вид '1 234 567.89 ₽'."""
    return f"{value:>15,.2f} ₽"


def _truncate(name: str, width: int = 40) -> str:
    """Обрезает длинное имя с многоточием."""
    if len(name) <= width:
        return name
    return name[: width - 1] + "…"


def print_counterparty_turnover(counterparties: list[dict]) -> None:
    """Вывод оборотов по контрагентам. 'Прочие (без контрагента)' — ниже черты."""

    named = []
    other = None
    for cp in counterparties:
        if cp['name'] == 'Прочие (без контрагента)':
            other = cp
        else:
            named.append(cp)

    print()
    print("=" * 90)
    print("  ОБОРОТЫ ПО КОНТРАГЕНТАМ")
    print("=" * 90)

    print(f"\n  {'Контрагент':<40} {'Приход':>16} {'Расход':>16} {'Внутр.':>16}")
    print("  " + "-" * 86)

    total_income = 0.0
    total_expense = 0.0
    total_internal = 0.0

    # --- Именованные контрагенты ---
    for cp in named:
        name = _truncate(cp['name'], 38)
        inc = f"{cp['income']:>16,.2f}" if cp['income'] else f"{'—':>16}"
        exp = f"{cp['expense']:>16,.2f}" if cp['expense'] else f"{'—':>16}"
        int_ = f"{cp['internal']:>16,.2f}" if cp['internal'] else f"{'—':>16}"
        print(f"  {name:<40} {inc} {exp} {int_}")

        total_income += cp['income']
        total_expense += cp['expense']
        total_internal += cp['internal']

    # --- Прочие (без контрагента) ---
    if other is not None:
        label = "Прочие (без контрагента)"
        inc = f"{other['income']:>16,.2f}" if other['income'] else f"{'—':>16}"
        exp = f"{other['expense']:>16,.2f}" if other['expense'] else f"{'—':>16}"
        int_ = f"{other['internal']:>16,.2f}" if other['internal'] else f"{'—':>16}"
        print("  " + "-" * 86)
        print(f"  {label:<40} {inc} {exp} {int_}")

        total_income += other['income']
        total_expense += other['expense']
        total_internal += other['internal']

    # --- Итоги ---
    print("  " + "-" * 86)
    print(f"  {'ИТОГО':<40} "
          f"{total_income:>16,.2f} "
          f"{total_expense:>16,.2f} "
          f"{total_internal:>16,.2f}")

    net = total_income - total_expense
    print()
    print(f"  САЛЬДО (приход − расход):                                 {net:>16,.2f} ₽")
    print(f"  Контрагентов: {len(named)} + прочие")
    print("=" * 90)


def print_category_turnover(categories: list[dict]) -> None:
    """Вывод оборотов по категориям с итогами и сальдо."""
    print()
    print("=" * 78)
    print("  ОБОРОТЫ ПО КАТЕГОРИЯМ")
    print("=" * 78)

    print(f"\n  {'Категория':<28} {'Приход':>16} {'Расход':>16} {'Внутр.':>16}")
    print("  " + "-" * 74)

    total_income = 0.0
    total_expense = 0.0
    total_internal = 0.0

    for c in categories:
        inc = f"{c['income']:>16,.2f}" if c['income'] else f"{'—':>16}"
        exp = f"{c['expense']:>16,.2f}" if c['expense'] else f"{'—':>16}"
        int_ = f"{c['internal']:>16,.2f}" if c['internal'] else f"{'—':>16}"
        print(f"  {c['category']:<28} {inc} {exp} {int_}")

        total_income += c['income']
        total_expense += c['expense']
        total_internal += c['internal']

    # Итоги
    print("  " + "-" * 74)
    print(f"  {'ИТОГО':<28} "
          f"{total_income:>16,.2f} "
          f"{total_expense:>16,.2f} "
          f"{total_internal:>16,.2f}")

    # Сальдо
    net = total_income - total_expense
    print()
    print(f"  САЛЬДО (приход − расход):                            {net:>16,.2f} ₽")
    print(f"  Категорий: {len(categories)}")
    print("=" * 78)
