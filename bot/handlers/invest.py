from bot.instance import bot_tg
from bot.decorator import require_role_cb, Role, get_user_role, ROLE_LEVEL
from bot.keyboard import (
    invest_summary_keyboard,
    invest_positions_keyboard,
    invest_chart_keyboard, invest_metrics_keyboard,
)
from invest.sync import sync_invest_operations
from reports.invest_report import (
    build_invest_report,
    build_all_positions,
    format_invest_summary,
    format_invest_positions_page,
    POSITIONS_PER_PAGE,
)
from reports.index_report import build_index_chart


@bot_tg.callback_query_handler(func=lambda c: c.data == 'menu_invest')
@require_role_cb(Role.ADMIN)
def cb_invest(call):
    bot_tg.answer_callback_query(call.id, "🔄 Обновляю портфель...")

    try:
        sync_invest_operations()
        report = build_invest_report()
        text = format_invest_summary(report)
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    total = len(report.get('all_positions', []))

    try:
        bot_tg.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='HTML',
            reply_markup=invest_summary_keyboard(total),
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise


@bot_tg.callback_query_handler(func=lambda c: c.data.startswith('invest_all_'))
@require_role_cb(Role.ADMIN)
def cb_invest_all(call):
    try:
        page = int(call.data.rsplit('_', 1)[1])
    except (ValueError, IndexError):
        page = 0

    try:
        all_positions = build_all_positions()
    except Exception as e:
        bot_tg.answer_callback_query(call.id, f"Ошибка: {e}", show_alert=True)
        return

    total = len(all_positions)
    total_pages = max(1, (total + POSITIONS_PER_PAGE - 1) // POSITIONS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    text = format_invest_positions_page(all_positions, page)

    try:
        bot_tg.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='HTML',
            reply_markup=invest_positions_keyboard(page, total_pages),
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise

    bot_tg.answer_callback_query(call.id)


@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_chart')
@require_role_cb(Role.ADMIN)
def cb_invest_chart(call):
    """
    ВАЖНО: НЕ вызываем backfill — график только визуализирует данные.
    Если данные устарели, они обновятся при следующем синке (menu_invest).
    """
    bot_tg.answer_callback_query(call.id, "📈 Строю график...")

    try:
        path = build_index_chart()
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка графика: {e}")
        return

    try:
        with open(path, 'rb') as f:
            bot_tg.send_photo(
                call.message.chat.id,
                f,
                caption="📈 <b>Динамика портфеля</b>\n\n"
                        "Верхний график — индекс полной доходности (TWR),\n"
                        "старт = 100. Сравнение с IMOEX, RTSI, RGBI, MCFTR.",
                parse_mode='HTML',
                reply_markup=invest_chart_keyboard(),
            )
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка отправки: {e}")
        return

    try:
        bot_tg.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


@bot_tg.callback_query_handler(func=lambda c: c.data == 'noop')
def cb_noop(call):
    bot_tg.answer_callback_query(call.id)


@bot_tg.message_handler(commands=['invest'])
def cmd_invest(message):
    role = get_user_role(message.from_user.id)
    if ROLE_LEVEL[role] < ROLE_LEVEL[Role.MODERATOR]:
        bot_tg.reply_to(message, "⛔ Недостаточно прав")
        return

    try:
        sync_invest_operations()
        report = build_invest_report()
        text = format_invest_summary(report)
    except Exception as e:
        bot_tg.reply_to(message, f"⚠️ Ошибка: {e}")
        return

    total = len(report.get('all_positions', []))
    bot_tg.send_message(
        message.chat.id,
        text,
        parse_mode='HTML',
        reply_markup=invest_summary_keyboard(total),
    )


@bot_tg.message_handler(commands=['chart'])
def cmd_chart(message):
    role = get_user_role(message.from_user.id)
    if ROLE_LEVEL[role] < ROLE_LEVEL[Role.MODERATOR]:
        bot_tg.reply_to(message, "⛔ Недостаточно прав")
        return

    try:
        path = build_index_chart()
    except Exception as e:
        bot_tg.reply_to(message, f"⚠️ Ошибка: {e}")
        return

    with open(path, 'rb') as f:
        bot_tg.send_photo(
            message.chat.id,
            f,
            caption="📈 Индекс полной доходности (TWR)",
            reply_markup=invest_chart_keyboard(),
        )

# ============================================================
# Метрики (rolling, волатильность, Sharpe)
# ============================================================

# ============================================================
# Метрики с выбором бенчмарка
# ============================================================

# Все доступные бенчмарки
BENCHMARKS = {
    'rgbi':  ('BBG000V0SJ39', 'RGBI'),
    'imoex': ('BBG00KDWPPW2', 'IMOEX'),
    'mcftr': ('BBG00G6B6TB1', 'MCFTR'),
    'rtsi':  ('BBG000NJ9048', 'RTSI'),
}


def _render_metrics(call, benchmark_key: str):
    """Общий рендер метрик для выбранного бенчмарка."""
    figi, name = BENCHMARKS.get(benchmark_key, BENCHMARKS['rgbi'])

    try:
        from invest.metrics import build_metrics_report
        from reports.invest_report import format_metrics

        metrics = build_metrics_report(
            benchmark_figi=figi,
            benchmark_name=name,
        )
        text = format_metrics(metrics)
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка метрик: {e}")
        return

    try:
        bot_tg.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='HTML',
            reply_markup=invest_metrics_keyboard(),
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise


@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_metrics')
@require_role_cb(Role.ADMIN)
def cb_invest_metrics(call):
    """Кнопка «📊 Метрики» — открывает с дефолтным бенчмарком (RGBI)."""
    bot_tg.answer_callback_query(call.id, "📊 Считаю метрики...")
    _render_metrics(call, 'rgbi')


@bot_tg.callback_query_handler(func=lambda c: c.data == 'metrics_vs_rgbi')
@require_role_cb(Role.ADMIN)
def cb_metrics_rgbi(call):
    bot_tg.answer_callback_query(call.id, "📊 Считаю метрики vs RGBI...")
    _render_metrics(call, 'rgbi')


@bot_tg.callback_query_handler(func=lambda c: c.data == 'metrics_vs_imoex')
@require_role_cb(Role.ADMIN)
def cb_metrics_imoex(call):
    bot_tg.answer_callback_query(call.id, "📊 Считаю метрики vs IMOEX...")
    _render_metrics(call, 'imoex')


@bot_tg.callback_query_handler(func=lambda c: c.data == 'metrics_vs_mcftr')
@require_role_cb(Role.ADMIN)
def cb_metrics_mcftr(call):
    bot_tg.answer_callback_query(call.id, "📊 Считаю метрики vs MCFTR...")
    _render_metrics(call, 'mcftr')


@bot_tg.callback_query_handler(func=lambda c: c.data == 'metrics_vs_rtsi')
@require_role_cb(Role.ADMIN)
def cb_metrics_rtsi(call):
    bot_tg.answer_callback_query(call.id, "📊 Считаю метрики vs RTSI...")
    _render_metrics(call, 'rtsi')


# ============================================================
# Структура портфеля (pie)
# ============================================================

@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_pie')
@require_role_cb(Role.ADMIN)
def cb_invest_pie(call):
    bot_tg.answer_callback_query(call.id, "🥧 Строю диаграмму...")
    try:
        from reports.portfolio_charts import build_portfolio_detailed_pie
        path = build_portfolio_detailed_pie()
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    with open(path, 'rb') as f:
        bot_tg.send_photo(
            call.message.chat.id,
            f,
            caption="🥧 <b>Структура портфеля</b>\nРаспределение активов по типам.",
            parse_mode='HTML',
            reply_markup=invest_chart_keyboard(),
        )

# ============================================================
# Доходы (купоны/дивиденды по месяцам)
# ============================================================

@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_income')
@require_role_cb(Role.ADMIN)
def cb_invest_income(call):
    bot_tg.answer_callback_query(call.id, "💰 Строю график доходов...")

    try:
        from reports.portfolio_charts import build_income_chart

        path = build_income_chart()
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    with open(path, 'rb') as f:
        bot_tg.send_photo(
            call.message.chat.id,
            f,
            caption="💰 <b>Динамика доходов по месяцам</b>\n"
                    "Купоны, дивиденды, погашения.",
            parse_mode='HTML',
            reply_markup=invest_chart_keyboard(),
        )

# ============================================================
# Сектора (pie)
# ============================================================

@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_sectors')
@require_role_cb(Role.ADMIN)
def cb_invest_sectors(call):
    bot_tg.answer_callback_query(call.id, "🏭 Строю распределение по секторам...")

    try:
        from reports.portfolio_charts import build_sectors_pie_chart
        path = build_sectors_pie_chart()
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    with open(path, 'rb') as f:
        bot_tg.send_photo(
            call.message.chat.id,
            f,
            caption="🏭 <b>Распределение по секторам</b>\n"
                    "Показывает концентрацию портфеля.",
            parse_mode='HTML',
            reply_markup=invest_chart_keyboard(),
        )


# ============================================================
# Атрибуция (pie)
# ============================================================

@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_attribution')
@require_role_cb(Role.ADMIN)
def cb_invest_attribution(call):
    bot_tg.answer_callback_query(call.id, "📉 Считаю атрибуцию...")

    try:
        from reports.portfolio_charts import build_attribution_pie_chart
        path = build_attribution_pie_chart()
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    with open(path, 'rb') as f:
        bot_tg.send_photo(
            call.message.chat.id,
            f,
            caption="📉 <b>Атрибуция доходности</b>\n"
                    "Из чего сложилась доходность портфеля.",
            parse_mode='HTML',
            reply_markup=invest_chart_keyboard(),
        )


# ============================================================
# Метрики по позициям
# ============================================================

@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_positions_metrics')
@require_role_cb(Role.ADMIN)
def cb_invest_positions_metrics(call):
    bot_tg.answer_callback_query(call.id, "📈 Считаю метрики по позициям...")

    try:
        from invest.position_metrics import build_position_metrics
        from reports.invest_report import format_position_metrics

        positions = build_position_metrics()
        text = format_position_metrics(positions)
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    try:
        bot_tg.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML',
            reply_markup=invest_chart_keyboard(),
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise


# ============================================================
# Ребалансировка
# ============================================================

@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_rebalance')
@require_role_cb(Role.ADMIN)
def cb_invest_rebalance(call):
    bot_tg.answer_callback_query(call.id, "⚖️ Считаю ребалансировку...")

    try:
        from invest.rebalance import build_rebalance_recommendations
        from reports.invest_report import format_rebalance

        report = build_rebalance_recommendations()
        text = format_rebalance(report)
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    try:
        bot_tg.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML',
            reply_markup=invest_chart_keyboard(),
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise


# ============================================================
# Целевые ориентиры
# ============================================================

@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_goals')
@require_role_cb(Role.ADMIN)
def cb_invest_goals(call):
    bot_tg.answer_callback_query(call.id, "🎯 Считаю прогресс...")

    try:
        from invest.goals import build_goals_report
        from reports.invest_report import format_goals

        report = build_goals_report()
        text = format_goals(report)
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    try:
        bot_tg.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML',
            reply_markup=invest_chart_keyboard(),
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise


# ============================================================
# Симуляция «что если»
# ============================================================

@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_simulation')
@require_role_cb(Role.ADMIN)
def cb_invest_simulation(call):
    bot_tg.answer_callback_query(call.id, "🔮 Считаю прогноз...")

    try:
        from invest.simulation import build_simulation
        from reports.invest_report import format_simulation

        report = build_simulation()
        text = format_simulation(report)
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    try:
        bot_tg.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML',
            reply_markup=invest_chart_keyboard(),
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise

# ============================================================
# Rolling Sharpe
# ============================================================

@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_rolling_sharpe')
@require_role_cb(Role.ADMIN)
def cb_invest_rolling_sharpe(call):
    bot_tg.answer_callback_query(call.id, "📈 Считаю rolling Sharpe...")

    try:
        from invest.rolling_metrics import build_rolling_sharpe_report
        from reports.invest_report import format_rolling_sharpe

        report = build_rolling_sharpe_report()
        text = format_rolling_sharpe(report)
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    # Отправляем текст
    try:
        bot_tg.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='HTML',
            reply_markup=invest_chart_keyboard(),
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            raise


@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_rolling_sharpe_chart')
@require_role_cb(Role.ADMIN)
def cb_invest_rolling_sharpe_chart(call):
    """График rolling Sharpe."""
    bot_tg.answer_callback_query(call.id, "📈 Строю график...")

    try:
        from reports.rolling_chart import build_rolling_sharpe_chart
        path = build_rolling_sharpe_chart()
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    with open(path, 'rb') as f:
        bot_tg.send_photo(
            call.message.chat.id,
            f,
            caption="📈 <b>Rolling Sharpe портфеля</b>\n\n"
                    "Верх: Sharpe за 30 и 90 дней.\n"
                    "Низ: волатильность за 30 дней.",
            parse_mode='HTML',
            reply_markup=invest_chart_keyboard(),
        )


# bot/invest.py (добавить в конец файла)

@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_treemap')
@require_role_cb(Role.ADMIN)
def cb_invest_treemap(call):
    bot_tg.answer_callback_query(call.id, "🔥 Строю тепловую карту...")
    try:
        from reports.portfolio_charts import build_pnl_treemap
        path = build_pnl_treemap()
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    with open(path, 'rb') as f:
        bot_tg.send_photo(call.message.chat.id, f,
                          caption="🔥 <b>Тепловая карта P&L</b>\nРазмер блока = стоимость, Цвет = P&L",
                          parse_mode='HTML', reply_markup=invest_chart_keyboard())


@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_detailed_pie')
@require_role_cb(Role.ADMIN)
def cb_invest_detailed_pie(call):
    bot_tg.answer_callback_query(call.id, "🥧 Строю детальную структуру...")
    try:
        from reports.portfolio_charts import build_portfolio_detailed_pie
        path = build_portfolio_detailed_pie()
    except Exception as e:
        bot_tg.send_message(call.message.chat.id, f"⚠️ Ошибка: {e}")
        return

    with open(path, 'rb') as f:
        bot_tg.send_photo(call.message.chat.id, f, caption="🥧 <b>Структура по бумагам</b>", parse_mode='HTML',
                          reply_markup=invest_chart_keyboard())


# Оценка всего портфеля (Фундаментал)
@bot_tg.callback_query_handler(func=lambda c: c.data == 'invest_fundamental_score')
@require_role_cb(Role.ADMIN)
def cb_invest_fund_score(call):
    bot_tg.answer_callback_query(call.id, "🧠 Считаю средний балл портфеля...")

    from database.instrument_crud import InstrumentCrud
    from database.db import Session
    from invest.scoring.final_verdict import final_verdict

    with Session() as s:
        positions = InstrumentCrud(s).get_all()  # Берем все, потом отфильтруем

    # (Здесь нужна логика получения текущих позиций из API, чтобы не оценивать то, чего нет)
    # Для простоты — оцениваем топ-10 по весу из парсера портфеля:
    from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio
    from config.settings import ACCOUNTS_ID

    tickers = []
    with TInvestPortfolioClient() as client:
        for acc in ACCOUNTS_ID:
            raw = client.fetch_portfolio(acc)
            if not raw: continue
            p = parse_portfolio(raw)
            # Берем только акции
            for pos in p['positions']:
                if pos['instrument_type'] == 'share' and pos['ticker']:
                    tickers.append(pos['ticker'])

    if not tickers:
        bot_tg.send_message(call.message.chat.id, "Нет акций в портфеле для оценки.")
        return

    results = []
    for t in set(tickers):
        try:
            res = final_verdict(t, auto_backfill=False)  # Без парсинга, чтоб быстро
            if 'score' in res:
                results.append((t, res['score'], res['action']))
        except:
            pass

    if not results:
        bot_tg.send_message(call.message.chat.id, "Не удалось оценить (нет фундаментала).")
        return

    avg_score = sum(r[1] for r in results) / len(results)
    text = f"🧠 <b>Фундаментальный балл портфеля: {avg_score:.1f}/100</b>\n\n"
    for t, sc, act in sorted(results, key=lambda x: x[1], reverse=True):
        text += f"  • <b>{t}</b>: {act} ({sc})\n"

    bot_tg.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=invest_chart_keyboard())