from bot.instance import bot_tg
from bot.decorator import (
    require_role, require_role_cb, Role, clear_role_cache, get_user_role,
)
from bot.keyboard import back_to_menu, users_menu
from database.db import Session
from database.crud import UserCrud, CashWithdrawalCrud, BalanceAdjustmentCrud, CrudDB
from reports.report import build_detailed_report


def _fmt(value: float) -> str:
    return f"{value:,.2f} ₽".replace(",", " ")


# ============ Меню ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'menu_users')
@require_role_cb(Role.ADMIN)
def cb_users(call):
    bot_tg.edit_message_text(
        "👥 <b>Управление пользователями</b>\n\nВыбери действие:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=users_menu(),
    )
    bot_tg.answer_callback_query(call.id)


@bot_tg.callback_query_handler(func=lambda c: c.data == 'menu_settings')
@require_role_cb(Role.ADMIN)
def cb_settings(call):
    bot_tg.edit_message_text(
        "⚙️ Настройки:\n...",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=back_to_menu(),
    )
    bot_tg.answer_callback_query(call.id)


# ============ Список пользователей ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'user_list')
@require_role_cb(Role.ADMIN)
def cb_user_list(call):
    with Session() as session:
        users = UserCrud(session).get_all()

    if not users:
        text = "Пользователей пока нет."
    else:
        lines = []
        for u in users[:30]:
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

    bot_tg.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=users_menu(),
    )
    bot_tg.answer_callback_query(call.id)


@bot_tg.callback_query_handler(func=lambda c: c.data == 'user_stats')
@require_role_cb(Role.ADMIN)
def cb_user_stats(call):
    with Session() as session:
        users = UserCrud(session).get_all()

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
    bot_tg.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=users_menu(),
    )
    bot_tg.answer_callback_query(call.id)


# ============ Роли ============

@bot_tg.message_handler(commands=['add_mod'])
@require_role(Role.ADMIN)
def cmd_add_mod(message):
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot_tg.reply_to(message, "Использование: <code>/add_mod 123456789</code>",
                        parse_mode='HTML')
        return

    user_id = int(parts[1])
    with Session() as session:
        ok = UserCrud(session).set_role(user_id, Role.MODERATOR)

    clear_role_cache()

    if ok:
        bot_tg.reply_to(message, f"✅ <code>{user_id}</code> назначен модератором.",
                        parse_mode='HTML')
        try:
            bot_tg.send_message(user_id, "🎉 Вам выдан доступ модератора. Напишите /start.")
        except Exception:
            pass
    else:
        bot_tg.reply_to(
            message,
            f"❌ Пользователь <code>{user_id}</code> не найден.\n"
            f"<i>Он должен сначала написать боту /start.</i>",
            parse_mode='HTML',
        )


@bot_tg.message_handler(commands=['del_mod'])
@require_role(Role.ADMIN)
def cmd_del_mod(message):
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot_tg.reply_to(message, "Использование: <code>/del_mod 123456789</code>",
                        parse_mode='HTML')
        return

    user_id = int(parts[1])
    with Session() as session:
        ok = UserCrud(session).set_role(user_id, Role.USER)

    clear_role_cache()

    if ok:
        bot_tg.reply_to(message, f"✅ <code>{user_id}</code> теперь обычный пользователь.",
                        parse_mode='HTML')
    else:
        bot_tg.reply_to(message, f"❌ Пользователь <code>{user_id}</code> не найден.",
                        parse_mode='HTML')


# ============ FSM: назначить/снять модератора ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'user_add_mod')
@require_role_cb(Role.ADMIN)
def cb_user_add_mod(call):
    msg = bot_tg.edit_message_text(
        "➕ Введи <b>ID</b> пользователя, которого назначить модератором:\n"
        "<i>Например: 123456789</i>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot_tg.answer_callback_query(call.id)
    bot_tg.register_next_step_handler(msg, process_add_mod)


def process_add_mod(message):
    text = (message.text or '').strip().lstrip('@')
    if not text.isdigit():
        bot_tg.send_message(message.chat.id, "⚠️ ID должен быть числом. Отмена.")
        return

    user_id = int(text)
    with Session() as session:
        ok = UserCrud(session).set_role(user_id, Role.MODERATOR)

    clear_role_cache()

    if ok:
        bot_tg.send_message(
            message.chat.id,
            f"✅ <code>{user_id}</code> назначен модератором.",
            parse_mode='HTML',
        )
        try:
            bot_tg.send_message(user_id, "🎉 Вам выдан доступ модератора. Напишите /start.")
        except Exception:
            pass
    else:
        bot_tg.send_message(
            message.chat.id,
            f"❌ Пользователь <code>{user_id}</code> не найден.\n"
            f"<i>Он должен сначала написать боту /start.</i>",
            parse_mode='HTML',
        )


@bot_tg.callback_query_handler(func=lambda c: c.data == 'user_del_mod')
@require_role_cb(Role.ADMIN)
def cb_user_del_mod(call):
    msg = bot_tg.edit_message_text(
        "➖ Введи <b>ID</b> модератора, которого снять:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot_tg.answer_callback_query(call.id)
    bot_tg.register_next_step_handler(msg, process_del_mod)


def process_del_mod(message):
    text = (message.text or '').strip().lstrip('@')
    if not text.isdigit():
        bot_tg.send_message(message.chat.id, "⚠️ ID должен быть числом. Отмена.")
        return

    user_id = int(text)
    with Session() as session:
        ok = UserCrud(session).set_role(user_id, Role.USER)

    clear_role_cache()

    if ok:
        bot_tg.send_message(
            message.chat.id,
            f"✅ <code>{user_id}</code> теперь обычный пользователь.",
            parse_mode='HTML',
        )
    else:
        bot_tg.send_message(
            message.chat.id,
            f"❌ Пользователь <code>{user_id}</code> не найден.",
            parse_mode='HTML',
        )


# ============ FSM: бан/разбан ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'user_ban')
@require_role_cb(Role.ADMIN)
def cb_user_ban(call):
    msg = bot_tg.edit_message_text(
        "🚫 Введи <b>ID</b> пользователя для бана/разбана:\n"
        "<i>Если забанен — разбанится, и наоборот.</i>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot_tg.answer_callback_query(call.id)
    bot_tg.register_next_step_handler(msg, process_ban)


def process_ban(message):
    text = (message.text or '').strip().lstrip('@')
    if not text.isdigit():
        bot_tg.send_message(message.chat.id, "⚠️ ID должен быть числом. Отмена.")
        return

    user_id = int(text)
    if user_id == message.from_user.id:
        bot_tg.send_message(message.chat.id, "⚠️ Нельзя забанить себя.")
        return

    with Session() as session:
        crud = UserCrud(session)
        current = crud.is_banned(user_id)
        ok = crud.set_banned(user_id, not current)

    if not ok:
        bot_tg.send_message(
            message.chat.id,
            f"❌ Пользователь <code>{user_id}</code> не найден.",
            parse_mode='HTML',
        )
        return

    action = "разбанен" if current else "забанен"
    bot_tg.send_message(
        message.chat.id,
        f"✅ <code>{user_id}</code> {action}.",
        parse_mode='HTML',
    )


# ============ Снятие наличных (ADMIN) ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'cash_withdraw')
@require_role_cb(Role.ADMIN)
def cb_cash_withdraw(call):
    msg = bot_tg.edit_message_text(
        "💸 <b>Снятие наличных</b>\n\n"
        "Введи <b>сумму</b> в рублях (только число):\n"
        "<i>Например: 15000 или 15000.50</i>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot_tg.answer_callback_query(call.id)
    bot_tg.register_next_step_handler(msg, process_cash_withdraw)


def process_cash_withdraw(message):
    text = (message.text or '').strip().replace(',', '.').replace(' ', '')

    if text.lower() in ('отмена', 'cancel', '/cancel'):
        bot_tg.send_message(message.chat.id, "Отменено.")
        return

    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        bot_tg.send_message(
            message.chat.id,
            "⚠️ Введи положительное число. Попробуй ещё раз или напиши «отмена».",
        )
        bot_tg.register_next_step_handler(message, process_cash_withdraw)
        return

    with Session() as session:
        CashWithdrawalCrud(session).add(
            amount=amount,
            created_by=message.from_user.id,
            comment='',
        )
        total = CashWithdrawalCrud(session).total()

    bot_tg.send_message(
        message.chat.id,
        f"✅ Снятие <b>{amount:,.2f} ₽</b> сохранено.\n"
        f"Всего снятий за всё время: <b>{total:,.2f} ₽</b>",
        parse_mode='HTML',
    )


@bot_tg.message_handler(commands=['cash_list'])
@require_role(Role.ADMIN)
def cmd_cash_list(message):
    with Session() as session:
        items = CashWithdrawalCrud(session).get_all()
    if not items:
        bot_tg.reply_to(message, "Снятий пока нет.")
        return
    lines = [
        f"<code>{i.id}</code>  {float(i.amount):,.2f} ₽  "
        f"{i.created_at.strftime('%d.%m.%Y %H:%M') if i.created_at else '—'}"
        for i in items[:20]
    ]
    bot_tg.reply_to(
        message,
        "💸 <b>Снятия наличных</b>\n\n" + "\n".join(lines) +
        "\n\nУдалить: <code>/cash_del &lt;id&gt;</code>",
        parse_mode='HTML',
    )


@bot_tg.message_handler(commands=['cash_del'])
@require_role(Role.ADMIN)
def cmd_cash_del(message):
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot_tg.reply_to(message, "Использование: <code>/cash_del 5</code>",
                        parse_mode='HTML')
        return
    with Session() as session:
        ok = CashWithdrawalCrud(session).delete(int(parts[1]))
    bot_tg.reply_to(message, "✅ Удалено." if ok else "❌ Запись не найдена.")


# ============ Корректировка остатка (ADMIN) ============

@bot_tg.callback_query_handler(func=lambda c: c.data == 'balance_adjust')
@require_role_cb(Role.ADMIN)
def cb_balance_adjust(call):
    with Session() as session:
        adj_total = BalanceAdjustmentCrud(session).total()
        cash_total = CashWithdrawalCrud(session).total()
        report = build_detailed_report(
            CrudDB(session),
            cash_withdrawn=cash_total,
            balance_adjustment=adj_total,
        )

    real = report.get('Реальный остаток на счету', 0)

    msg = bot_tg.edit_message_text(
        f"⚖️ <b>Корректировка остатка</b>\n\n"
        f"Сейчас в отчёте: <code>{_fmt(real)}</code>\n"
        f"Текущая корректировка: <code>{_fmt(adj_total)}</code>\n\n"
        f"Введи <b>сумму</b> корректировки (число):\n"
        f"  • <code>+23940</code> — увеличить остаток\n"
        f"  • <code>-23940</code> — уменьшить остаток\n"
        f"  • <code>0</code> — добавить нулевую запись\n\n"
        f"<i>Отмена: «отмена»</i>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=back_to_menu(),
    )
    bot_tg.answer_callback_query(call.id)
    bot_tg.register_next_step_handler(msg, process_balance_adjust)


def process_balance_adjust(message):
    text = (message.text or '').strip().replace(',', '.').replace(' ', '')

    if text.lower() in ('отмена', 'cancel', '/cancel'):
        bot_tg.send_message(message.chat.id, "Отменено.")
        return

    try:
        amount = float(text)
    except ValueError:
        bot_tg.send_message(
            message.chat.id,
            "⚠️ Введи число. Попробуй ещё раз или напиши «отмена».",
        )
        bot_tg.register_next_step_handler(message, process_balance_adjust)
        return

    with Session() as session:
        BalanceAdjustmentCrud(session).add(
            amount=amount,
            created_by=message.from_user.id,
            comment='',
        )
        adj_total = BalanceAdjustmentCrud(session).total()
        cash_total = CashWithdrawalCrud(session).total()
        report = build_detailed_report(
            CrudDB(session),
            cash_withdrawn=cash_total,
            balance_adjustment=adj_total,
        )

    real = report.get('Реальный остаток на счету', 0)
    free = report.get('Свободный остаток (после налогов и взносов)', 0)

    bot_tg.send_message(
        message.chat.id,
        f"✅ Корректировка <b>{amount:+,.2f} ₽</b> сохранена.\n\n"
        f"Общая корректировка: <code>{_fmt(adj_total)}</code>\n"
        f"Реальный остаток: <code>{_fmt(real)}</code>\n"
        f"Свободный остаток: <code>{_fmt(free)}</code>\n\n"
        f"История: /adjust_list",
        parse_mode='HTML',
    )


@bot_tg.message_handler(commands=['adjust_list'])
@require_role(Role.ADMIN)
def cmd_adjust_list(message):
    with Session() as session:
        items = BalanceAdjustmentCrud(session).get_all(30)
        total = BalanceAdjustmentCrud(session).total()

    if not items:
        bot_tg.reply_to(message, "Корректировок пока нет.")
        return

    lines = [
        f"<code>{i.id}</code>  {float(i.amount):+,.2f} ₽  "
        f"{i.created_at.strftime('%d.%m.%Y %H:%M') if i.created_at else '—'}"
        for i in items
    ]
    bot_tg.reply_to(
        message,
        f"⚖️ <b>Корректировки остатка</b>\n\n"
        + "\n".join(lines)
        + f"\n\nИТОГО: <b>{total:+,.2f} ₽</b>"
        + "\n\nУдалить: <code>/adjust_del &lt;id&gt;</code>",
        parse_mode='HTML',
    )


@bot_tg.message_handler(commands=['adjust_del'])
@require_role(Role.ADMIN)
def cmd_adjust_del(message):
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot_tg.reply_to(message, "Использование: <code>/adjust_del 5</code>",
                        parse_mode='HTML')
        return
    with Session() as session:
        ok = BalanceAdjustmentCrud(session).delete(int(parts[1]))
    bot_tg.reply_to(message, "✅ Удалено." if ok else "❌ Запись не найдена.")