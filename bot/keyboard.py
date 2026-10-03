from telebot import types

from bot.decorator import Role, ROLE_LEVEL


def main_menu(role: Role) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)

    if role == Role.USER:
        markup.add(
            types.InlineKeyboardButton('🔑 Запросить доступ', callback_data='accept')
        )

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
            types.InlineKeyboardButton('👥 Пользователи', callback_data='menu_users'),
            types.InlineKeyboardButton('⚙️ Настройки', callback_data='menu_settings'),
            types.InlineKeyboardButton('💸 Снятие наличных', callback_data='cash_withdraw')
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