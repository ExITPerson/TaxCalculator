from bot.instance import bot
from bot.decorator import (
    require_role, require_role_cb, Role, clear_role_cache, get_user_role,
)
from bot.keyboard import back_to_menu, users_menu
from database.db import Session
from database.crud import UserCrud, CashWithdrawalCrud


# ============ Меню ============

@bot.callback_query_handler(func=lambda c: c.data == 'menu_users')
@require_role_cb(Role.ADMIN)
def cb_users(call):
    bot.edit_message_text(
        "👥 <b>Управление пользователями</b>\n\nВыбери действие:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=users_menu(),
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == 'menu_settings')
@require_role_cb(Role.ADMIN)
def cb_settings(call):
    bot.edit_message_text(
        "⚙️ Настройки:\n...",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=back_to_menu(),
    )
    bot.answer_callback_query(call.id)


# ============ Список пользователей ============

@bot.callback_query_handler(func=lambda c: c.data == 'user_list')
@require_role_cb(Role.ADMIN)
def cb_user_list(call):
    with Session() as session:
        users = UserCrud(session).get_all()

    if not users:
        text = "Пользователей пока нет."
    else:
        lines = []
        for u in users[:30]:
            # FIX: роль вычисляем через get_user_role — учитывает ADMIN_IDS
            role = get_user_role(u.user_id)
            name = u.full_name or u.username or f"id{u.user_id}"
            icon = {'admin': '👑', 'moderator': '🛡', 'user': '👤'}.get(role.value, '❓')
            banned = ' 🚫' if u.is_banned else ''
            lines.append(
                f"{icon} <b>{name}</b>{banned}\n"
                f"   <code>{u.user_id}</code>  @{u.username or '—'}\n"
                f"   роль: <i>{role.value}</i>"
            )
        text = "👥 <b>Пользователи</b>\n\n" + "\n\n".join(lines)
        if len(users) > 30:
            text += f"\n\n… и ещё {len(users) - 30}"

    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=users_menu(),
    )
    bot.answer_callback_query(call.id)


# ============ Статистика ============

@bot.callback_query_handler(func=lambda c: c.data == 'user_stats')
@require_role_cb(Role.ADMIN)
def cb_user_stats(call):
    with Session() as session:
        users = UserCrud(session).get_all()

    # FIX: считаем по get_user_role, а не по БД
    counts = {'admin': 0, 'moderator': 0, 'user': 0}
    for u in users:
        role = get_user_role(u.user_id)
        counts[role.value] = counts.get(role.value, 0) + 1

    total = len(users)
    banned = sum(1 for u in users if u.is_banned)

    text = (
        "📊 <b>Статистика пользователей</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Всего:         <code>{total}</code>\n"
        f"👑 Админов:       <code>{counts['admin']}</code>\n"
        f"🛡 Модераторов:   <code>{counts['moderator']}</code>\n"
        f"👤 Пользователей: <code>{counts['user']}</code>\n"
        f"🚫 Забанено:      <code>{banned}</code>"
    )
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=users_menu(),
    )
    bot.answer_callback_query(call.id)


# ============ Команды для админа ============

@bot.message_handler(commands=['add_mod'])
@require_role(Role.ADMIN)
def cmd_add_mod(message):
    """ /add_mod <user_id> """
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Использование: <code>/add_mod 123456789</code>",
                     parse_mode='HTML')
        return

    user_id = int(parts[1])
    with Session() as session:
        ok = UserCrud(session).set_role(user_id, Role.MODERATOR)

    clear_role_cache()

    if ok:
        bot.reply_to(message, f"✅ <code>{user_id}</code> назначен модератором.",
                     parse_mode='HTML')
        try:
            bot.send_message(user_id, "🎉 Вам выдан доступ модератора. Напишите /start.")
        except Exception:
            pass
    else:
        bot.reply_to(
            message,
            f"❌ Пользователь <code>{user_id}</code> не найден.\n"
            f"<i>Он должен сначала написать боту /start.</i>",
            parse_mode='HTML',
        )


@bot.message_handler(commands=['del_mod'])
@require_role(Role.ADMIN)
def cmd_del_mod(message):
    """ /del_mod <user_id> """
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Использование: <code>/del_mod 123456789</code>",
                     parse_mode='HTML')
        return

    user_id = int(parts[1])
    with Session() as session:
        ok = UserCrud(session).set_role(user_id, Role.USER)

    clear_role_cache()

    if ok:
        bot.reply_to(message, f"✅ <code>{user_id}</code> теперь обычный пользователь.",
                     parse_mode='HTML')
    else:
        bot.reply_to(message, f"❌ Пользователь <code>{user_id}</code> не найден.",
                     parse_mode='HTML')


# ============ FSM: назначить модератора через кнопку ============

@bot.callback_query_handler(func=lambda c: c.data == 'user_add_mod')
@require_role_cb(Role.ADMIN)
def cb_user_add_mod(call):
    msg = bot.edit_message_text(
        "➕ Введи <b>ID</b> пользователя, которого назначить модератором:\n"
        "<i>Например: 123456789</i>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler(msg, process_add_mod)


def process_add_mod(message):
    text = (message.text or '').strip().lstrip('@')
    if not text.isdigit():
        bot.send_message(message.chat.id, "⚠️ ID должен быть числом. Отмена.")
        return

    user_id = int(text)
    with Session() as session:
        ok = UserCrud(session).set_role(user_id, Role.MODERATOR)

    clear_role_cache()

    if ok:
        bot.send_message(
            message.chat.id,
            f"✅ <code>{user_id}</code> назначен модератором.",
            parse_mode='HTML',
        )
        try:
            bot.send_message(user_id, "🎉 Вам выдан доступ модератора. Напишите /start.")
        except Exception:
            pass
    else:
        bot.send_message(
            message.chat.id,
            f"❌ Пользователь <code>{user_id}</code> не найден.\n"
            f"<i>Он должен сначала написать боту /start.</i>",
            parse_mode='HTML',
        )


# ============ FSM: снять модератора ============

@bot.callback_query_handler(func=lambda c: c.data == 'user_del_mod')
@require_role_cb(Role.ADMIN)
def cb_user_del_mod(call):
    msg = bot.edit_message_text(
        "➖ Введи <b>ID</b> модератора, которого снять:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler(msg, process_del_mod)


def process_del_mod(message):
    text = (message.text or '').strip().lstrip('@')
    if not text.isdigit():
        bot.send_message(message.chat.id, "⚠️ ID должен быть числом. Отмена.")
        return

    user_id = int(text)
    with Session() as session:
        ok = UserCrud(session).set_role(user_id, Role.USER)

    clear_role_cache()

    if ok:
        bot.send_message(
            message.chat.id,
            f"✅ <code>{user_id}</code> теперь обычный пользователь.",
            parse_mode='HTML',
        )
    else:
        bot.send_message(
            message.chat.id,
            f"❌ Пользователь <code>{user_id}</code> не найден.",
            parse_mode='HTML',
        )


# ============ FSM: бан/разбан ============

@bot.callback_query_handler(func=lambda c: c.data == 'user_ban')
@require_role_cb(Role.ADMIN)
def cb_user_ban(call):
    msg = bot.edit_message_text(
        "🚫 Введи <b>ID</b> пользователя для бана/разбана:\n"
        "<i>Если забанен — разбанится, и наоборот.</i>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler(msg, process_ban)


def process_ban(message):
    text = (message.text or '').strip().lstrip('@')
    if not text.isdigit():
        bot.send_message(message.chat.id, "⚠️ ID должен быть числом. Отмена.")
        return

    user_id = int(text)
    if user_id == message.from_user.id:
        bot.send_message(message.chat.id, "⚠️ Нельзя забанить себя.")
        return

    with Session() as session:
        crud = UserCrud(session)
        current = crud.is_banned(user_id)
        ok = crud.set_banned(user_id, not current)

    if not ok:
        bot.send_message(
            message.chat.id,
            f"❌ Пользователь <code>{user_id}</code> не найден.",
            parse_mode='HTML',
        )
        return

    action = "разбанен" if current else "забанен"
    bot.send_message(
        message.chat.id,
        f"✅ <code>{user_id}</code> {action}.",
        parse_mode='HTML',
    )

@bot.callback_query_handler(func=lambda c: c.data == 'cash_withdraw')
@require_role_cb(Role.ADMIN)
def cb_cash_withdraw(call):
    msg = bot.edit_message_text(
        "💸 <b>Снятие наличных</b>\n\n"
        "Введи <b>сумму</b> в рублях (только число):\n"
        "<i>Например: 15000 или 15000.50</i>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler(msg, process_cash_withdraw)


def process_cash_withdraw(message):
    text = (message.text or '').strip().replace(',', '.').replace(' ', '')

    # отмена
    if text.lower() in ('отмена', 'cancel', '/cancel'):
        bot.send_message(message.chat.id, "Отменено.")
        return

    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ Введи положительное число. Попробуй ещё раз или напиши «отмена».",
        )
        bot.register_next_step_handler(message, process_cash_withdraw)
        return

    with Session() as session:
        CashWithdrawalCrud(session).add(
            amount=amount,
            created_by=message.from_user.id,
            comment='',
        )
        total = CashWithdrawalCrud(session).total()

    bot.send_message(
        message.chat.id,
        f"✅ Снятие <b>{amount:,.2f} ₽</b> сохранено.\n"
        f"Всего снятий за всё время: <b>{total:,.2f} ₽</b>",
        parse_mode='HTML',
    )