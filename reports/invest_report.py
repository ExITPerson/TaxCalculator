import logging

from config.settings import ACCOUNTS_ID
from database.db import Session
from database.crud import InvestCrud
from invest.analytics import PortfolioAnalytics
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio
from invest.metrics import build_metrics_report

logger = logging.getLogger(__name__)

POSITIONS_PER_PAGE = 15
TOP_ON_SUMMARY = 20


def _fmt(value: float) -> str:
    return f"{value:,.2f} ₽".replace(",", " ")


def _fmt_qty(qty: float) -> str:
    if qty == int(qty):
        return str(int(qty))
    return f"{qty:.4g}"


# ---------- Сбор данных ----------

def build_invest_report(account_id: str | None = None) -> dict:
    """Сводный отчёт: операции из БД + текущий портфель из API."""
    with Session() as session:
        crud = InvestCrud(session)
        analytics = PortfolioAnalytics(crud, account_id=account_id)
        report = analytics.summary()
        income_by_figi = crud.income_by_figi()

    portfolios: dict[str, dict] = {}
    with TInvestPortfolioClient() as client:
        accounts = [account_id] if account_id else ACCOUNTS_ID
        for acc_id in accounts:
            raw = client.fetch_portfolio(acc_id)
            if not raw:
                continue
            portfolios[acc_id] = parse_portfolio(raw)

    report['portfolios'] = portfolios
    report['income_by_figi'] = income_by_figi
    report['all_positions'] = collect_all_positions(portfolios, income_by_figi)
    return report


def build_all_positions() -> list[dict]:
    """Только плоский список позиций (для постраничного списка)."""
    with Session() as session:
        income_by_figi = InvestCrud(session).income_by_figi()

    portfolios: dict[str, dict] = {}
    with TInvestPortfolioClient() as client:
        for acc_id in ACCOUNTS_ID:
            raw = client.fetch_portfolio(acc_id)
            if raw:
                portfolios[acc_id] = parse_portfolio(raw)

    return collect_all_positions(portfolios, income_by_figi)


def collect_all_positions(portfolios: dict, income_by_figi: dict) -> list[dict]:
    """Плоский список позиций по всем счетам, отсортированный по стоимости."""
    result = []

    for acc_id, portfolio in portfolios.items():
        for p in portfolio.get('positions', []):
            qty = p['quantity']
            cur = p['current_price']
            value = qty * cur

            if value <= 0:
                continue

            figi = p['figi']
            ticker = p.get('ticker') or p['figi'][:20]
            income = income_by_figi.get(figi, {})

            result.append({
                'account_id': acc_id,
                'figi': figi,
                'ticker': ticker,
                'instrument_type': p.get('instrument_type', ''),
                'quantity': qty,
                'average_price': p['average_price'],
                'current_price': cur,
                'expected_yield': p['expected_yield'],
                'value': value,
                'coupon': income.get('coupon', 0.0),
                'dividend': income.get('dividend', 0.0),
                'bond_repayment': income.get('bond_repayment', 0.0),
                'amortization': income.get('amortization', 0.0),
                'income_total': sum(income.values()),
            })

    result.sort(key=lambda x: x['value'], reverse=True)
    return result


# ---------- Основной отчёт ----------

def format_invest_summary(report: dict, top_n: int = TOP_ON_SUMMARY) -> str:
    deposits = report.get('deposits', 0)
    withdrawals = report.get('withdrawals', 0)
    net = report.get('net_invested', 0)
    fees = report.get('fees', 0)
    income = report.get('income', 0)
    income_by_type = report.get('income_by_type', {})
    portfolios = report.get('portfolios', {})
    all_positions = report.get('all_positions', [])

    total_value = sum(p.get('total_amount_portfolio', 0) for p in portfolios.values())
    total_expected_yield = sum(p.get('expected_yield', 0) for p in portfolios.values())

    lines = [
        "📈 <b>Инвестиционный портфель</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
        "💵 <b>Денежные потоки</b>",
        f"  • Пополнения:      <code>{_fmt(deposits)}</code>",
        f"  • Выводы:          <code>{_fmt(withdrawals)}</code>",
        f"  • Вложено (net):   <code>{_fmt(net)}</code>",
        "",
        "💰 <b>Доходы по активам</b>",
    ]

    if income_by_type:
        labels = {
            'coupon': 'Купоны',
            'dividend': 'Дивиденды',
            'bond_repayment': 'Погашение облигаций',
            'amortization': 'Амортизация',
        }
        for kind, amount in income_by_type.items():
            lines.append(f"  • {labels.get(kind, kind)}: <code>{_fmt(amount)}</code>")
        lines.append(f"  • <b>Итого: {_fmt(income)}</b>")
    else:
        lines.append("  <i>Доходов пока нет</i>")

    lines += [
        "",
        f"🧾 Комиссии и налоги: <code>{_fmt(fees)}</code>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>Текущий портфель</b>",
        f"  • Стоимость:       <code>{_fmt(total_value)}</code>",
        f"  • Нереализ. P&L:   <code>{_fmt(total_expected_yield)}</code>",
        "",
    ]

    if all_positions:
        lines.append(f"🏆 <b>Топ-{min(top_n, len(all_positions))} по стоимости</b>")
        for p in all_positions[:top_n]:
            lines.append(_format_position_line(p))
        if len(all_positions) > top_n:
            lines.append(f"  <i>… ещё {len(all_positions) - top_n} позиций</i>")
    else:
        lines.append("<i>Позиций нет</i>")

    return "\n".join(lines)


# ---------- Постраничный список ----------

def format_invest_positions_page(
    all_positions: list[dict],
    page: int,
    per_page: int = POSITIONS_PER_PAGE,
) -> str:
    total = len(all_positions)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))

    start = page * per_page
    end = start + per_page
    chunk = all_positions[start:end]

    lines = [
        f"📋 <b>Все позиции</b>  ({page + 1}/{total_pages})",
        f"Всего: {total}",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    for p in chunk:
        lines.append(_format_position_line(p))
        lines.append("")    # пустая строка между позициями

    return "\n".join(lines)


# ---------- Форматирование одной позиции ----------

def _format_position_line(p: dict) -> str:
    """Форматирует одну позицию: цена, P&L, купоны, дивиденды."""
    ticker = p.get('ticker') or p['figi'][:20]
    qty = p['quantity']
    avg = p['average_price']
    cur = p['current_price']
    pnl = p['expected_yield']
    value = p['value']

    # Процент P&L по цене
    if avg > 0 and qty > 0:
        pnl_pct = (cur - avg) / avg * 100
        pct_str = f" ({pnl_pct:+.2f}%)"
    else:
        pct_str = ""

    # Строка доходности по купонам/дивидендам
    parts = []
    if p.get('coupon', 0):
        parts.append(f"Купоны: {_fmt(p['coupon'])}")
    if p.get('dividend', 0):
        parts.append(f"Дивиденды: {_fmt(p['dividend'])}")
    if p.get('bond_repayment', 0):
        parts.append(f"Погашение: {_fmt(p['bond_repayment'])}")
    if p.get('amortization', 0):
        parts.append(f"Аморт.: {_fmt(p['amortization'])}")

    income_line = ""
    if parts:
        income_line = "\n    💰 " + "  |  ".join(parts)

    return (
        f"  • <code>{ticker}</code>  [{p['account_id']}]\n"
        f"    {_fmt_qty(qty)} × {_fmt(avg)} → {_fmt(cur)}\n"
        f"    {_fmt(value)}  |  <code>{_fmt(pnl)}</code>{pct_str}"
        f"{income_line}"
    )

def format_metrics(metrics: dict) -> str:
    """HTML-блок с метриками для Telegram."""
    if 'error' in metrics:
        return f"<i>{metrics['error']}</i>"

    rfr = metrics.get('risk_free_rate', 0.13) * 100
    bench_name = metrics.get('benchmark_name', 'RGBI')
    bench_ret = metrics.get('benchmark_return_pct')
    ir = metrics.get('information_ratio')

    lines = [
        "📊 <b>Метрики портфеля</b>",
        f"  • Период: <code>{metrics['days_total']}</code> дней",
        f"  • Доходность: <code>{metrics['total_return_pct']:+.2f}%</code>",
        "",
        "📈 <b>Rolling-доходность</b>",
    ]

    for label, value in [
        ('7 дней', metrics['rolling_7d']),
        ('30 дней', metrics['rolling_30d']),
        ('90 дней', metrics['rolling_90d']),
    ]:
        if value is None:
            lines.append(f"  • {label}: <i>мало данных</i>")
        else:
            emoji = '🟢' if value >= 0 else '🔴'
            lines.append(f"  • {label}: {emoji} <code>{value:+.2f}%</code>")

    # Доходность vs бенчмарк
    if bench_ret is not None:
        diff = metrics['total_return_pct'] - bench_ret
        emoji = '🟢' if diff >= 0 else '🔴'
        lines += [
            "",
            f"🎯 <b>Доходность vs {bench_name}</b>",
            f"  • Портфель:  <code>{metrics['total_return_pct']:+.2f}%</code>",
            f"  • {bench_name}:  <code>{bench_ret:+.2f}%</code>",
            f"  • {emoji} Разница: <code>{diff:+.2f} п.п.</code>",
        ]

    # Риск-метрики
    sharpe = metrics.get('sharpe', 0)
    sortino = metrics.get('sortino', 0)
    calmar = metrics.get('calmar', 0)

    sharpe_emoji = '🟢' if sharpe > 0.5 else ('🟡' if sharpe > 0 else '🔴')
    sortino_emoji = '🟢' if sortino > 0.5 else ('🟡' if sortino > 0 else '🔴')
    calmar_emoji = '🟢' if calmar > 1 else ('🟡' if calmar > 0.3 else '🔴')

    lines += [
        "",
        "⚠️ <b>Метрики риска</b>",
        f"  • Волатильность: <code>{metrics['volatility_annual_pct']:.2f}%</code>",
        f"  • Sharpe:  {sharpe_emoji} <code>{sharpe:+.2f}</code>",
        f"  • Sortino: {sortino_emoji} <code>{sortino:+.2f}</code>",
        f"  • Calmar:  {calmar_emoji} <code>{calmar:+.2f}</code>",
        "",
        "📉 <b>Просадки</b>",
        f"  • Максимальная: <code>{metrics['max_drawdown_pct']:.2f}%</code>",
        f"  • Текущая: <code>{metrics['current_drawdown_pct']:.2f}%</code>",
    ]

    # Beta / Relative return / IR
    beta = metrics.get('beta', 0)
    beta_comment = (
        'слабая связь с рынком' if abs(beta) < 0.3
        else 'спокойнее рынка' if beta < 1
        else 'волатильнее рынка'
    )

    lines += [
        "",
        f"📊 <b>Beta / Информация vs {bench_name}</b>",
        f"  • Beta: <code>{beta:+.2f}</code>  <i>({beta_comment})</i>",
    ]

    if bench_ret is not None:
        relative = metrics['total_return_pct'] - bench_ret
        emoji = '🟢' if relative >= 0 else '🔴'
        ir_str = f"<code>{ir:+.2f}</code>" if ir is not None else "<i>мало данных</i>"

        lines += [
            f"  • {emoji} Сверхдоходность: <code>{relative:+.2f} п.п.</code>",
            f"  • Information Ratio: {ir_str}",
        ]

    # Интерпретация
    lines += [
        "",
        "<b>Что это значит:</b>",
    ]

    if bench_ret is not None:
        relative = metrics['total_return_pct'] - bench_ret
        if relative > 0:
            lines.append(f"  🟢 Обгоняешь {bench_name} на "
                          f"<code>{relative:+.2f} п.п.</code>")
        else:
            lines.append(f"  🔴 Отстаёшь от {bench_name} на "
                          f"<code>{relative:+.2f} п.п.</code>")

    if ir is not None:
        if ir > 1.0:
            ir_comment = 'отличная сверхдоходность'
        elif ir > 0.5:
            ir_comment = 'хорошая сверхдоходность'
        elif ir > 0:
            ir_comment = 'слабая сверхдоходность'
        else:
            ir_comment = 'нет сверхдоходности'
        lines.append(f"  • IR {ir:+.2f} — {ir_comment}")

    if sharpe < 0:
        lines.append(f"  • Sharpe {sharpe:+.2f} — риск не окупается при rf={rfr:.1f}%")

    lines.append("")
    lines.append(f"<i>Безрисковая ставка: {rfr:.1f}%. "
                  f"При высокой ставке Sharpe и Alpha облигационного "
                  f"портфеля часто отрицательные — смотри на "
                  f"сверхдоходность и IR.</i>")

    return "\n".join(lines)

def format_position_metrics(positions: list[dict]) -> str:
    """HTML-таблица с метриками по позициям."""
    if not positions:
        return "<i>Нет данных</i>"

    # Сортируем по стоимости
    positions = sorted(
        positions,
        key=lambda p: p['quantity'] * p['current_price'],
        reverse=True,
    )

    lines = ["📊 <b>Метрики по позициям</b>", ""]

    for p in positions[:15]:
        ticker = p.get('ticker') or p['figi'][:20]
        vol = p.get('volatility')
        sharpe = p.get('sharpe')

        vol_str = f"{vol:.1f}%" if vol is not None else "—"
        sharpe_str = f"{sharpe:+.2f}" if sharpe is not None else "—"
        sharpe_emoji = (
            '🟢' if sharpe and sharpe > 0.5
            else '🟡' if sharpe and sharpe > 0
            else '🔴' if sharpe is not None
            else ''
        )

        lines.append(
            f"<code>{ticker:<20}</code>\n"
            f"  Волат: <code>{vol_str}</code>  |  "
            f"Sharpe: {sharpe_emoji} <code>{sharpe_str}</code>"
        )

    if len(positions) > 15:
        lines.append(f"<i>… ещё {len(positions) - 15} позиций</i>")

    return "\n".join(lines)


def format_rebalance(report: dict) -> str:
    """HTML-блок с рекомендациями по ребалансировке."""
    if 'error' in report:
        return f"<i>{report['error']}</i>"

    lines = [
        "⚖️ <b>Ребалансировка портфеля</b>",
        f"Всего: <code>{report['total']:,.0f} ₽</code>",
        "",
    ]

    for r in report['recommendations']:
        emoji = '✅' if not r['needs_rebalance'] else '⚠️'
        action_emoji = (
            '🟢' if r['action'] == 'купить'
            else '🔴' if r['action'] == 'продать'
            else '⚪'
        )

        lines.append(
            f"{emoji} <b>{r['asset']}</b>\n"
            f"  Текущая: <code>{r['current_pct']:.1f}%</code> "
            f"({r['current_value']:,.0f} ₽)\n"
            f"  Цель:    <code>{r['target_pct']:.1f}%</code> "
            f"({r['target_value']:,.0f} ₽)\n"
            f"  Отклонение: <code>{r['deviation_pct']:+.1f}%</code>\n"
            f"  {action_emoji} {r['action'].capitalize()} на "
            f"<code>{abs(r['diff_rub']):,.0f} ₽</code>"
        )

    if report['needs_rebalance']:
        lines += ["", "⚠️ <i>Ребалансировка рекомендуется</i>"]
    else:
        lines += ["", "✅ <i>Портфель сбалансирован</i>"]

    return "\n".join(lines)


def format_goals(report: dict) -> str:
    """HTML-блок с целевыми ориентирами."""
    if 'error' in report:
        return f"<i>{report['error']}</i>"

    progress = report['progress_pct']
    bar_filled = int(progress / 5)
    bar = '█' * bar_filled + '░' * (20 - bar_filled)

    lines = [
        "🎯 <b>Целевой ориентир</b>",
        f"  Цель: <code>+{report['target_pct']:.1f}%</code> за год",
        f"  Сейчас: <code>{report['current_pct']:+.2f}%</code>",
        "",
        f"  [{bar}] {progress:.0f}%",
        "",
        f"  Осталось: <code>{report['remaining_pct']:+.2f}%</code>",
        f"  Дней до конца года: <code>{report['days_left']}</code>",
        f"  Требуемая доходность: <code>{report['required_annual_pct']:+.1f}%</code> годовых",
    ]

    if report['is_achievable']:
        lines.append("✅ <i>Цель достижима</i>")
    else:
        lines.append("⚠️ <i>Цель может быть нереалистичной</i>")

    return "\n".join(lines)


def format_simulation(report: dict) -> str:
    """HTML-блок с симуляцией."""
    if 'error' in report:
        return f"<i>{report['error']}</i>"

    lines = [
        "🔮 <b>Симуляция на год</b>",
        f"  Текущая стоимость: <code>{report['current_value']:,.0f} ₽</code>",
        f"  Годовая доходность: <code>{report['annual_return_pct']:+.2f}%</code>",
        f"  Годовые купоны/дивы: <code>{report['annual_income_rub']:,.0f} ₽</code>",
        "",
        "<b>Сценарии:</b>",
    ]

    for key, s in report['scenarios'].items():
        emoji = (
            '🟢' if s['diff_pct'] > 0
            else '🔴' if s['diff_pct'] < 0
            else '⚪'
        )
        lines.append(
            f"  {emoji} {s['label']}\n"
            f"     <code>{s['value']:,.0f} ₽</code> "
            f"({s['diff_pct']:+.2f}%)"
        )

    return "\n".join(lines)

def format_rolling_sharpe(report: dict) -> str:
    """HTML-блок с rolling Sharpe для Telegram."""
    if 'error' in report:
        return f"<i>{report['error']}</i>"

    current = report['current']
    rfr = report.get('risk_free_rate', 0.13) * 100

    lines = [
        "📊 <b>Rolling Sharpe ratio</b>",
        f"  Период: <code>{report['days_total']}</code> дней",
        f"  Безрисковая ставка: <code>{rfr:.1f}%</code>",
        "",
        "📈 <b>Sharpe по окнам</b>",
    ]

    for w in (7, 30, 90):
        c = current.get(w)
        if not c:
            continue

        if not c['has_enough_data']:
            lines.append(f"  • {w} дней: <i>мало данных</i>")
            continue

        sharpe = c['sharpe']
        emoji = '🟢' if sharpe > 0.5 else ('🟡' if sharpe > 0 else '🔴')

        lines.append(f"  • {w} дней: {emoji} <code>{sharpe:+.2f}</code>")

    vol_30 = current.get(30, {}).get('volatility')
    if vol_30 is not None:
        lines += [
            "",
            "⚠️ <b>Текущие метрики (30 дней)</b>",
            f"  • Волатильность: <code>{vol_30:.2f}%</code>",
        ]

    lines += [
        "",
        "<b>Интерпретация:</b>",
        "  🟢 &gt; 0.5 — хорошо (риск окупается)",
        "  🟡 0…0.5 — приемлемо",
        "  🔴 &lt; 0 — плохо (риск не окупается)",
        "",
        "<i>При высокой ключевой ставке (16%) "
        "Sharpe будет отрицательным даже у качественного портфеля.</i>",
    ]

    return "\n".join(lines)