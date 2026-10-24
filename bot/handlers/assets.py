# bot/assets.py
import logging
import html
import re
from bot.instance import bot_tg
from bot.decorator import require_role_cb, Role
from bot.keyboard import back_to_menu, assets_menu, score_result_keyboard, top_assets_keyboard
from database.db import Session, CachedScoreDB
from database.crud import CachedScoreCrud
from database.instrument_crud import InstrumentCrud
from invest.scoring.final_verdict import final_verdict
from invest.bond_score import evaluate_bond
from invest.bond_resolver import ensure_bond_in_db

logger = logging.getLogger(__name__)


# ============ Меню ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'menu_assets')
@require_role_cb(Role.ADMIN)
def cb_menu_assets(call):
    bot_tg.edit_message_text(
        "🔍 <b>Оценка активов</b>\n\nВыбери действие:",
        call.message.chat.id, call.message.message_id,
        parse_mode='HTML', reply_markup=assets_menu(),
    )
    bot_tg.answer_callback_query(call.id)


# ============ Оценка АКЦИИ (с кэшем) ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'asset_stock')
@require_role_cb(Role.ADMIN)
def cb_asset_stock(call):
    msg = bot_tg.edit_message_text(
        "📈 Введи <b>тикер акции</b> (например, <code>SBER</code>, <code>GAZP</code>):",
        call.message.chat.id, call.message.message_id,
        parse_mode='HTML', reply_markup=back_to_menu(),
    )
    bot_tg.answer_callback_query(call.id)
    bot_tg.register_next_step_handler(msg, process_stock_ticker, force=False)


def process_stock_ticker(message, force=False):
    ticker = (message.text or '').strip().upper()
    if not ticker: return

    # Проверяем кэш (если не принудительное обновление)
    if not force:
        with Session() as s:
            cached = CachedScoreCrud(s).get(ticker, 'stock', ttl_hours=12)
            if cached:
                msg = bot_tg.send_message(message.chat.id, cached.text_result, parse_mode='HTML',
                                          reply_markup=score_result_keyboard())
                # Сохраняем тикер для кнопки "Обновить"
                bot_tg.register_next_step_handler(msg, process_stock_ticker, force=True)
                return

    msg = bot_tg.send_message(message.chat.id, f"⏳ Считаю мультипликаторы для <b>{html.escape(ticker)}</b>...",
                              parse_mode='HTML')

    try:
        result = final_verdict(ticker, auto_backfill=True)

        emoji = {"BUY": "🟢", "HOLD": "🟡", "AVOID": "🔴", "STRONG_AVOID": "⛔"}.get(result['action'], "⚪")

        lines = [
            f"{emoji} <b>{html.escape(result['ticker'])}</b> [{html.escape(result['kind'])}]",
            f"Вердикт: <b>{html.escape(result['action'])}</b> (score {result['score']}/100)",
            ""
        ]

        if result['critical']:
            lines.append("⛔ <b>Критично:</b>\n" + "\n".join(f"  • {html.escape(c)}" for c in result['critical']))

        if result['info']:
            lines.append("\n✅ <b>Плюсы:</b>\n" + "\n".join(f"  • {html.escape(r)}" for r in result['info'][:5]))

        if result['warnings']:
            lines.append("\n⚠️ <b>Риски:</b>\n" + "\n".join(f"  • {html.escape(w)}" for w in result['warnings'][:5]))

        if result.get('dcf_data'):
            d = result['dcf_data']
            lines.append(
                f"\n💰 <b>DCF:</b> Fair {d['fair_price']} ₽ vs Current {d['current_price']} ₽ ({d['upside_pct']:+.1f}%)"
            )

        text = "\n".join(lines)

        # Сохраняем в кэш
        with Session() as s:
            CachedScoreCrud(s).save(ticker, 'stock', result['score'], result['action'], text)

        bot_tg.edit_message_text(text, message.chat.id, msg.message_id, parse_mode='HTML',
                                 reply_markup=score_result_keyboard())

    except Exception as e:
        logger.error(f"Ошибка скоринга {ticker}: {e}")
        bot_tg.edit_message_text(f"⚠️ Ошибка: {html.escape(str(e))}", message.chat.id, msg.message_id,
                                 reply_markup=assets_menu())


# ============ Оценка ОБЛИГАЦИИ ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'asset_bond')
@require_role_cb(Role.ADMIN)
def cb_asset_bond(call):
    msg = bot_tg.edit_message_text("📜 Введи <b>ISIN</b> облигации:", call.message.chat.id, call.message.message_id,
                                   parse_mode='HTML', reply_markup=back_to_menu())
    bot_tg.answer_callback_query(call.id)
    bot_tg.register_next_step_handler(msg, process_bond_isin)


def process_bond_isin(message):
    isin = (message.text or '').strip().upper()
    if not isin: return

    msg = bot_tg.send_message(message.chat.id, f"⏳ Оцениваю <b>{html.escape(isin)}</b>...", parse_mode='HTML')

    try:
        figi = ensure_bond_in_db(isin, save=True)
        if not figi: raise ValueError("Не найдена в API")
        res = evaluate_bond(figi)
        if 'error' in res: raise ValueError(res['error'])

        emoji = {"BUY": "🟢", "HOLD": "🟡", "AVOID": "🔴"}.get(res['verdict'], "⚪")
        text = (
            f"{emoji} <b>{html.escape(res['ticker'])}</b> — {html.escape(res['verdict'])}\n"
            f"YTM: <code>{res['ytm'] or 0:.2f}%</code> | Купон: <code>{res['coupon'] or 0:.1f}%</code>\n"
            f"Дюрация: <code>{html.escape(res['duration_human'])}</code> | Рейтинг: <code>{html.escape(res['rating'] or '—')}</code>\n\n"
        )
        if res['reasons']:
            text += "✅ <b>Плюсы:</b>\n" + "\n".join(f"  • {html.escape(r)}" for r in res['reasons'][:3]) + "\n"
        if res['warnings']:
            text += "\n⚠️ <b>Риски:</b>\n" + "\n".join(f"  • {html.escape(w)}" for w in res['warnings'][:3])

        bot_tg.edit_message_text(text, message.chat.id, msg.message_id, parse_mode='HTML', reply_markup=assets_menu())

    except Exception as e:
        bot_tg.edit_message_text(f"⚠️ Ошибка: {html.escape(str(e))}", message.chat.id, msg.message_id,
                                 reply_markup=assets_menu())


# ============ СРАВНЕНИЕ (Compare) ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'asset_compare')
@require_role_cb(Role.ADMIN)
def cb_asset_compare(call):
    msg = bot_tg.edit_message_text("⚔️ Введи два тикера через пробел (например, <code>SBER GAZP</code>):",
                                   call.message.chat.id, call.message.message_id, parse_mode='HTML',
                                   reply_markup=back_to_menu())
    bot_tg.answer_callback_query(call.id)
    bot_tg.register_next_step_handler(msg, process_compare)


def process_compare(message):
    parts = (message.text or '').split()
    if len(parts) != 2:
        bot_tg.send_message(message.chat.id, "⚠️ Нужно ровно два тикера.")
        return

    t1, t2 = parts[0].upper(), parts[1].upper()
    msg = bot_tg.send_message(message.chat.id, f"⏳ Сравниваю <b>{html.escape(t1)}</b> и <b>{html.escape(t2)}</b>...",
                              parse_mode='HTML')

    try:
        r1 = final_verdict(t1, auto_backfill=True)
        r2 = final_verdict(t2, auto_backfill=True)

        def fmt(r):
            return f"{r['action']} ({r['score']}/100)"

        text = (
            f"⚔️ <b>Сравнение акций</b>\n\n"
            f"<b>{html.escape(t1)}</b>: {fmt(r1)}\n"
            f"<b>{html.escape(t2)}</b>: {fmt(r2)}\n\n"
            f"<i>Победитель: {html.escape(t1 if r1['score'] > r2['score'] else t2)}</i>"
        )
        bot_tg.edit_message_text(text, message.chat.id, msg.message_id, parse_mode='HTML', reply_markup=assets_menu())
    except Exception as e:
        bot_tg.edit_message_text(f"⚠️ Ошибка: {html.escape(str(e))}", message.chat.id, msg.message_id)


# ============ ТОП ИДЕЙ (Screener) ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'asset_top')
@require_role_cb(Role.ADMIN)
def cb_asset_top(call):
    bot_tg.edit_message_text(
        "🏆 <b>Топ активов</b>\n\nВыбери категорию:",
        call.message.chat.id, call.message.message_id,
        parse_mode='HTML', reply_markup=top_assets_keyboard()
    )
    bot_tg.answer_callback_query(call.id)


@bot_tg.callback_query_handler(func=lambda c: c.data == 'top_stocks_15')
@require_role_cb(Role.ADMIN)
def cb_top_stocks_15(call):
    bot_tg.answer_callback_query(call.id, "⏳ Ищу лучшие акции...")

    with Session() as s:
        rows = s.query(CachedScoreDB).filter(
            CachedScoreDB.score_type == 'stock'
        ).order_by(
            CachedScoreDB.score_value.desc()
        ).limit(15).all()

    if not rows:
        bot_tg.send_message(call.message.chat.id,
                            "⚠️ Кэш пуст. Планировщик обновит данные ночью (или запустите refresh_scores.py).")
        return

    text = "🏆 <b>Топ-15 акций по Score</b>\n\n"
    for i, r in enumerate(rows, 1):
        emoji = {"BUY": "🟢", "HOLD": "🟡", "AVOID": "🔴", "STRONG_AVOID": "⛔"}.get(r.verdict, "⚪")
        text += f"{i}. {emoji} <b>{html.escape(r.ticker)}</b> — {html.escape(r.verdict)} (<code>{r.score_value:.0f}</code>)\n"

    text += "\n<i>* Чтобы получить полную оценку, нажмите «Оценить акцию»</i>"

    bot_tg.edit_message_text(
        text, call.message.chat.id, call.message.message_id,
        parse_mode='HTML', reply_markup=top_assets_keyboard()
    )


@bot_tg.callback_query_handler(func=lambda c: c.data == 'top_bonds_20')
@require_role_cb(Role.ADMIN)
def cb_top_bonds_20(call):
    bot_tg.answer_callback_query(call.id, "⏳ Ищу лучшие облигации...")

    with Session() as s:
        rows = s.query(CachedScoreDB).filter(
            CachedScoreDB.score_type == 'bond'
        ).order_by(
            CachedScoreDB.verdict.asc(),
            CachedScoreDB.ticker.asc()
        ).limit(20).all()

    if not rows:
        bot_tg.send_message(call.message.chat.id, "⚠️ Кэш пуст. Запустите refresh_scores.py.")
        return

    text = "🏆 <b>Топ-20 облигаций</b>\n\n"
    for i, r in enumerate(rows, 1):
        emoji = {"BUY": "🟢", "HOLD": "🟡", "AVOID": "🔴"}.get(r.verdict, "⚪")
        text += f"{i}. {emoji} <b>{html.escape(r.ticker)}</b> — {html.escape(r.verdict)}\n"

    text += "\n<i>* Для детального анализа нажмите «Оценить облигацию»</i>"

    bot_tg.edit_message_text(
        text, call.message.chat.id, call.message.message_id,
        parse_mode='HTML', reply_markup=top_assets_keyboard()
    )


@bot_tg.callback_query_handler(func=lambda c: c.data == 'top_allocations')
@require_role_cb(Role.ADMIN)
def cb_top_allocations(call):
    bot_tg.answer_callback_query(call.id, "⚖️ Считаю рекомендуемые доли...")

    with Session() as s:
        stocks = s.query(CachedScoreDB).filter(
            CachedScoreDB.score_type == 'stock',
            CachedScoreDB.score_value > 0
        ).order_by(CachedScoreDB.score_value.desc()).limit(5).all()

        bonds = s.query(CachedScoreDB).filter(
            CachedScoreDB.score_type == 'bond',
            CachedScoreDB.verdict == 'BUY'
        ).limit(5).all()

    if not stocks and not bonds:
        bot_tg.send_message(call.message.chat.id, "⚠️ Нет данных для рекомендаций. Обновите кэш.")
        return

    text = "⚖️ <b>Рекомендуемые доли в портфеле</b>\n\n"

    if stocks:
        text += "📈 <b>Акции</b> (по весу Score):\n"
        total_score = sum(r.score_value for r in stocks)
        for r in stocks:
            weight = (r.score_value / total_score) * 100 if total_score > 0 else 0
            text += f"  • <b>{html.escape(r.ticker)}</b>: {weight:.1f}% (score {r.score_value:.0f})\n"

        text += "\n"

    if bonds:
        text += "📜 <b>Облигации</b> (равные доли):\n"
        weight_bond = 100.0 / len(bonds)
        for r in bonds:
            text += f"  • <b>{html.escape(r.ticker)}</b>: {weight_bond:.1f}%\n"

    if not bonds:
        text += "📜 <b>Облигации</b>: <i>Нет надежных идей (BUY)</i>\n"

    text += (
        "\n💡 <b>Совет:</b>\n"
        "Распределите 100% капитала между этими бумагами.\n"
        "Например: 40% в акции (по 8% на каждую из 5) и 60% в облигации (по 12% на каждую из 5)."
    )

    bot_tg.edit_message_text(
        text, call.message.chat.id, call.message.message_id,
        parse_mode='HTML', reply_markup=top_assets_keyboard()
    )


# ============ ПАКЕТНОЕ РЕДАКТИРОВАНИЕ РЕЙТИНГОВ ОБЛИГАЦИЙ ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'asset_bond_ratings')
@require_role_cb(Role.ADMIN)
def cb_asset_bond_ratings(call):
    msg = bot_tg.edit_message_text(
        "⚙️ <b>Настройка рейтингов облигаций (Пакетный режим)</b>\n\n"
        "Введи список <b>ISIN</b> или <b>FIGI</b> облигаций через запятую или пробел.\n"
        "Например: <code>RU000A10EJR5, RU000A10FWA1, TCS80A101X50</code>\n\n"
        "Можно ввести до 10 штук за раз.\n"
        "Или напиши <i>«отмена»</i>, чтобы выйти.",
        call.message.chat.id, call.message.message_id,
        parse_mode='HTML', reply_markup=back_to_menu()
    )
    bot_tg.answer_callback_query(call.id)
    bot_tg.register_next_step_handler(msg, process_bond_list)


def process_bond_list(message):
    text = (message.text or '').strip()
    if text.lower() in ('отмена', 'cancel', '/cancel'):
        bot_tg.send_message(message.chat.id, "Отменено.", reply_markup=assets_menu())
        return

    tickers = [t.strip().upper() for t in re.split(r'[,\s]+', text) if t.strip()]

    if not tickers:
        bot_tg.send_message(message.chat.id, "⚠️ Не найдено ни одного тикера. Попробуй снова.")
        return

    if len(tickers) > 10:
        bot_tg.send_message(message.chat.id, f"⚠️ Слишком много тикеров ({len(tickers)}). Максимум 10 за раз.")
        return

    # Сохраняем очередь в контексте бота
    state = {
        'queue': tickers,
        'current_idx': 0,
        'results': {}  # {figi: rating}
    }

    # Запускаем процесс
    ask_next_bond_rating(message.chat.id, state)


def ask_next_bond_rating(chat_id: int, state: dict):
    """Рекурсивно запрашивает рейтинг для следующей облигации из очереди."""
    if state['current_idx'] >= len(state['queue']):
        # Все облигации обработаны — сохраняем в БД
        save_bond_ratings_to_db(chat_id, state['results'])
        return

    ticker = state['queue'][state['current_idx']]

    # Пытаемся найти или создать облигацию в БД
    with Session() as s:
        crud = InstrumentCrud(s)
        info = crud.get_by_ticker(ticker)

        if not info:
            # Пытаемся найти через API и сохранить
            figi = ensure_bond_in_db(ticker, save=True)
            if figi:
                info = crud.get(figi)

        if not info:
            # Если даже API не помог — пропускаем
            bot_tg.send_message(chat_id, f"⚠️ <b>{html.escape(ticker)}</b> не найдена в API/БД. Пропускаем.")
            state['current_idx'] += 1
            ask_next_bond_rating(chat_id, state)
            return

        figi = info.figi
        current_rating = info.credit_rating or "не задан"
        display_ticker = info.ticker or ticker

    msg = bot_tg.send_message(
        chat_id,
        f"<b>[{state['current_idx'] + 1}/{len(state['queue'])}]</b> "
        f"📜 <b>{html.escape(display_ticker)}</b>\n"
        f"Текущий рейтинг: <b>{html.escape(current_rating)}</b>\n\n"
        f"Введи новый рейтинг <i>(например, AAA, AA+, BBB)</i>:\n"
        f"Или напиши <i>«пропустить»</i> / <i>«отмена»</i>.",
        parse_mode='HTML'
    )
    bot_tg.register_next_step_handler(msg, process_single_rating, state=state, figi=figi)


def process_single_rating(message, state: dict, figi: str):
    text = (message.text or '').strip().upper()

    if text.lower() in ('отмена', 'cancel', '/cancel'):
        bot_tg.send_message(message.chat.id, "❌ Отменено. Введенные данные не сохранены.", reply_markup=assets_menu())
        return

    if text.lower() in ('пропустить', 'skip', 'пропуск'):
        # Пропускаем, переходим к следующему
        state['current_idx'] += 1
        ask_next_bond_rating(message.chat.id, state)
        return

    # Валидация рейтинга
    if not any(c in text for c in ('A', 'B', 'C', 'D')):
        bot_tg.send_message(message.chat.id, "⚠️ Некорректный формат. Введи рейтинг (например, AAA) или «пропустить».")
        bot_tg.register_next_step_handler(message, process_single_rating, state=state, figi=figi)
        return

    # Сохраняем во временный словарь
    state['results'][figi] = text
    state['current_idx'] += 1

    # Переходим к следующему
    ask_next_bond_rating(message.chat.id, state)


def save_bond_ratings_to_db(chat_id: int, results: dict):
    """Сохраняет все собранные рейтинги в БД."""
    if not results:
        bot_tg.send_message(chat_id, "⚠️ Не было введено ни одного рейтинга.", reply_markup=assets_menu())
        return

    saved_count = 0
    with Session() as s:
        crud = InstrumentCrud(s)
        for figi, rating in results.items():
            info = crud.get(figi)
            if info:
                info.credit_rating = rating
                saved_count += 1
        s.commit()

    text = f"✅ <b>Успешно сохранено рейтингов: {saved_count}</b>\n\n"
    for figi, rating in results.items():
        with Session() as s:
            info = InstrumentCrud(s).get(figi)
            ticker = info.ticker if info else figi
        text += f"  • <b>{html.escape(ticker)}</b> → {html.escape(rating)}\n"

    bot_tg.send_message(chat_id, text, parse_mode='HTML', reply_markup=assets_menu())