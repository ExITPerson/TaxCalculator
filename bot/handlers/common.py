from bot.instance import bot_tg
from bot.decorator import get_user_role, Role, require_role
from bot.keyboard import main_menu
from database.crud import CashWithdrawalCrud
from database.db import Session


@bot_tg.message_handler(commands=['start'])
def send_welcome(message):
    role = get_user_role(message.from_user.id)
    name = message.from_user.first_name or 'друг'
    bot_tg.send_message(
        message.chat.id,
        f"Привет, {name}!\nРоль: <b>{role.value}</b>",
        parse_mode='HTML',
        reply_markup=main_menu(role),
    )


@bot_tg.message_handler(commands=['menu'])
def cmd_menu(message):
    role = get_user_role(message.from_user.id)
    bot_tg.send_message(
        message.chat.id,
        "Главное меню:",
        reply_markup=main_menu(role),
    )


@bot_tg.message_handler(commands=['whoami'])
def cmd_whoami(message):
    u = message.from_user
    role = get_user_role(u.id)
    bot_tg.reply_to(
        message,
        f"ID: <code>{u.id}</code>\n"
        f"Username: @{u.username or '—'}\n"
        f"Роль: <b>{role.value}</b>",
        parse_mode='HTML',
    )


@bot_tg.callback_query_handler(func=lambda c: c.data == 'back_to_main')
def cb_back_to_main(call):
    role = get_user_role(call.from_user.id)
    bot_tg.edit_message_text(
        "Главное меню:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=main_menu(role),
    )
    bot_tg.answer_callback_query(call.id)


@bot_tg.callback_query_handler(func=lambda c: c.data == 'accept')
def cb_request_access(call):
    """Запрос доступа — обычный юзер просит повышения."""
    u = call.from_user
    admin_ids = []
    from config.settings import ADMIN_IDS
    admin_ids = list(ADMIN_IDS)

    for admin_id in admin_ids:
        try:
            bot_tg.send_message(
                admin_id,
                f"🔔 <b>Запрос доступа</b>\n"
                f"Пользователь: <b>{u.full_name or u.username or u.id}</b>\n"
                f"ID: <code>{u.id}</code>\n"
                f"Username: @{u.username or '—'}\n\n"
                f"Назначить модератором: /add_mod {u.id}",
                parse_mode='HTML',
            )
        except Exception:
            pass

    bot_tg.answer_callback_query(call.id, "✅ Заявка отправлена админам", show_alert=True)

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


from bot.handlers.assets import process_stock_ticker, process_bond_isin

@bot_tg.message_handler(commands=['stock'])
@require_role(Role.ADMIN)
def cmd_stock(message):
    parts = message.text.split()
    if len(parts) == 2:
        # Если тикер передан сразу: /stock SBER
        message.text = parts[1]
        process_stock_ticker(message)
    else:
        msg = bot_tg.reply_to(message, "Введи тикер акции:")
        bot_tg.register_next_step_handler(msg, process_stock_ticker)

@bot_tg.message_handler(commands=['bond'])
@require_role(Role.ADMIN)
def cmd_bond(message):
    parts = message.text.split()
    if len(parts) == 2:
        message.text = parts[1]
        process_bond_isin(message)
    else:
        msg = bot_tg.reply_to(message, "Введи ISIN облигации:")
        bot_tg.register_next_step_handler(msg, process_bond_isin)