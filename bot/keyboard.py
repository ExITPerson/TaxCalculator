# bot/keyboard.py
from telebot import types
from bot.decorator import Role, ROLE_LEVEL


def main_menu(role: Role) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)

    if role == Role.USER:
        markup.add(types.InlineKeyboardButton('🔑 Запросить доступ', callback_data='accept'))

    if ROLE_LEVEL[role] >= ROLE_LEVEL[Role.MODERATOR]:
        markup.add(
            types.InlineKeyboardButton('📊 Отчёт', callback_data='menu_report'),
            types.InlineKeyboardButton('💰 Остаток', callback_data='menu_balance'),
        )
        markup.add(
            types.InlineKeyboardButton('📏 Лимит', callback_data='limit'),
        )

    if ROLE_LEVEL[role] >= ROLE_LEVEL[Role.ADMIN]:
        markup.add(
            types.InlineKeyboardButton('⚖️ Корректировка', callback_data='balance_adjust'),
        )
        markup.add(
            types.InlineKeyboardButton('📈 Портфель', callback_data='menu_invest'),
            types.InlineKeyboardButton('👥 Пользователи', callback_data='menu_users'),
            types.InlineKeyboardButton('⚙️ Настройки', callback_data='menu_settings'),
            types.InlineKeyboardButton('💸 Снятие наличных', callback_data='cash_withdraw'),
            types.InlineKeyboardButton('🔍 Оценка активов', callback_data='menu_assets'),
        )

    return markup


def back_to_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('⬅️ Назад', callback_data='back_to_main'))
    return markup


def users_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton('👥 Все пользователи', callback_data='user_list'),
        types.InlineKeyboardButton('➕ Назначить модератора', callback_data='user_add_mod'),
        types.InlineKeyboardButton('➖ Снять модератора', callback_data='user_del_mod'),
        types.InlineKeyboardButton('🚫 Забанить / разбанить', callback_data='user_ban'),
        types.InlineKeyboardButton('📊 Статистика', callback_data='user_stats'),
        types.InlineKeyboardButton('⬅️ Назад', callback_data='back_to_main'),
    )
    return markup


def invest_summary_keyboard(total_positions: int) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)

    markup.add(
        types.InlineKeyboardButton('📈 График', callback_data='invest_chart'),
        types.InlineKeyboardButton('📊 Метрики', callback_data='invest_metrics'),
    )
    markup.add(
        types.InlineKeyboardButton('🥧 Структура', callback_data='invest_pie'),
        types.InlineKeyboardButton('🔥 Тепловая карта', callback_data='invest_treemap'),  # НОВОЕ
    )
    markup.add(
        types.InlineKeyboardButton('🏭 Сектора', callback_data='invest_sectors'),
        types.InlineKeyboardButton('📉 Атрибуция', callback_data='invest_attribution'),
    )
    markup.add(
        types.InlineKeyboardButton('💰 Доходы', callback_data='invest_income'),
        types.InlineKeyboardButton('📈 Позиции', callback_data='invest_positions_metrics'),
    )
    markup.add(
        types.InlineKeyboardButton('⚖️ Ребаланс', callback_data='invest_rebalance'),
        types.InlineKeyboardButton('🎯 Цели', callback_data='invest_goals'),
    )
    markup.add(
        types.InlineKeyboardButton('🔮 Прогноз', callback_data='invest_simulation'),
        types.InlineKeyboardButton('📈 Sharpe', callback_data='invest_rolling_sharpe'),
    )

    if total_positions > 20:
        markup.add(types.InlineKeyboardButton(f'📋 Все позиции ({total_positions})', callback_data='invest_all_0'))

    markup.add(types.InlineKeyboardButton('⬅️ Назад', callback_data='back_to_main'))
    return markup


def invest_positions_keyboard(page: int, total_pages: int) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=3)
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton('⬅️', callback_data=f'invest_all_{page - 1}'))
    nav.append(types.InlineKeyboardButton(f'{page + 1}/{total_pages}', callback_data='noop'))
    if page < total_pages - 1: nav.append(types.InlineKeyboardButton('➡️', callback_data=f'invest_all_{page + 1}'))
    markup.add(*nav)
    markup.add(types.InlineKeyboardButton('📈 График', callback_data='invest_chart'))
    markup.add(types.InlineKeyboardButton('🏠 В портфель', callback_data='menu_invest'))
    return markup


def invest_chart_keyboard() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('📊 Метрики', callback_data='invest_metrics'),
        types.InlineKeyboardButton('📈 Sharpe', callback_data='invest_rolling_sharpe'),
    )
    markup.add(
        types.InlineKeyboardButton('🥧 Структура', callback_data='invest_pie'),
        types.InlineKeyboardButton('🔥 Тепловая карта', callback_data='invest_treemap'),
    )
    markup.add(
        types.InlineKeyboardButton('🏭 Сектора', callback_data='invest_sectors'),
        types.InlineKeyboardButton('📉 Атрибуция', callback_data='invest_attribution'),
    )
    markup.add(types.InlineKeyboardButton('📈 График Sharpe', callback_data='invest_rolling_sharpe_chart'))
    markup.add(types.InlineKeyboardButton('🏠 В портфель', callback_data='menu_invest'))
    return markup


def invest_metrics_keyboard() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton('vs RGBI', callback_data='metrics_vs_rgbi'),
        types.InlineKeyboardButton('vs IMOEX', callback_data='metrics_vs_imoex'),
        types.InlineKeyboardButton('vs MCFTR', callback_data='metrics_vs_mcftr'),
    )
    markup.add(types.InlineKeyboardButton('vs RTSI', callback_data='metrics_vs_rtsi'))
    markup.add(types.InlineKeyboardButton('⬅️ Назад', callback_data='menu_invest'))
    return markup


# --- НОВЫЕ КЛАВИАТУРЫ ДЛЯ ОЦЕНКИ ---

def assets_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('📈 Оценить акцию', callback_data='asset_stock'),
        types.InlineKeyboardButton('📜 Оценить облигацию', callback_data='asset_bond'),
    )
    markup.add(
        types.InlineKeyboardButton('⚔️ Сравнить акции', callback_data='asset_compare'),
        types.InlineKeyboardButton('🏆 Топ идей', callback_data='asset_top'),
    )
    markup.add(types.InlineKeyboardButton('⬅️ Назад', callback_data='back_to_main'))
    return markup

def top_assets_keyboard() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton('📈 Топ-15 акций', callback_data='top_stocks_15'),
        types.InlineKeyboardButton('📜 Топ-20 облигаций', callback_data='top_bonds_20'),
        types.InlineKeyboardButton('⚖️ Рекомендуемые доли', callback_data='top_allocations'),
        types.InlineKeyboardButton('⬅️ Назад', callback_data='menu_assets'),
    )
    return markup


def score_result_keyboard() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('🔄 Обновить данные', callback_data='refresh_current_score'),
        types.InlineKeyboardButton('⬅️ К оценке', callback_data='menu_assets'),
    )
    return markup
