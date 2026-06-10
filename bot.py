import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import BOT_TOKEN, PROVIDER_TOKEN, STARS_PACKAGES, ADMIN_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# ─── Состояния ────────────────────────────────────────────────────────────────

class OrderStates(StatesGroup):
    waiting_username = State()


# ─── /start ───────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Купить звёзды", callback_data="buy_stars")
    builder.button(text="ℹ️ Как это работает", callback_data="how_it_works")
    builder.adjust(1)

    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Здесь ты можешь купить <b>Telegram Stars ⭐</b> за <b>TON 💎</b>.\n\n"
        "Stars используются для:\n"
        "• Поддержки авторов и ботов\n"
        "• Покупки цифровых товаров\n"
        "• Отправки реакций\n\n"
        "Нажми кнопку ниже, чтобы выбрать пакет 👇",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )


# ─── Как работает ─────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "how_it_works")
async def how_it_works(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Купить звёзды", callback_data="buy_stars")
    builder.button(text="◀️ Назад", callback_data="back_start")
    builder.adjust(1)

    await callback.message.edit_text(
        "ℹ️ <b>Как это работает?</b>\n\n"
        "1️⃣ Выбери нужный пакет звёзд\n"
        "2️⃣ Введи свой Telegram username\n"
        "3️⃣ Оплати через TON\n"
        "4️⃣ Получи Stars в течение 5-10 минут ⏱\n\n"
        "💎 <b>Оплата</b> — через CryptoBot (TON).\n"
        "Твои данные защищены.\n\n"
        "❓ Вопросы — /help",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


# ─── Список пакетов ───────────────────────────────────────────────────────────

@dp.callback_query(F.data.in_({"buy_stars", "back_packages"}))
async def show_packages(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    for pkg in STARS_PACKAGES:
        label = f"⭐ {pkg['stars']} звёзд — {pkg['ton']} TON"
        builder.button(text=label, callback_data=f"pkg_{pkg['id']}")
    builder.button(text="◀️ Назад", callback_data="back_start")
    builder.adjust(1)

    await callback.message.edit_text(
        "⭐ <b>Выбери пакет звёзд</b>\n\n"
        + "\n".join(
            f"• <b>{p['stars']} Stars</b> = {p['ton']} TON (~{p['usd']}$)"
            for p in STARS_PACKAGES
        ),
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data == "back_start")
async def back_to_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Купить звёзды", callback_data="buy_stars")
    builder.button(text="ℹ️ Как это работает", callback_data="how_it_works")
    builder.adjust(1)

    await callback.message.edit_text(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Здесь ты можешь купить <b>Telegram Stars ⭐</b> за <b>TON 💎</b>.\n\n"
        "Stars используются для:\n"
        "• Поддержки авторов и ботов\n"
        "• Покупки цифровых товаров\n"
        "• Отправки реакций\n\n"
        "Нажми кнопку ниже, чтобы выбрать пакет 👇",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


# ─── Выбор пакета → запрос username ──────────────────────────────────────────

@dp.callback_query(F.data.startswith("pkg_"))
async def ask_username(callback: CallbackQuery, state: FSMContext):
    pkg_id = callback.data.replace("pkg_", "")
    pkg = next((p for p in STARS_PACKAGES if p["id"] == pkg_id), None)

    if not pkg:
        await callback.answer("❌ Пакет не найден", show_alert=True)
        return

    await state.set_state(OrderStates.waiting_username)
    await state.update_data(pkg_id=pkg_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="back_packages")
    builder.adjust(1)

    await callback.message.edit_text(
        f"⭐ <b>Пакет: {pkg['stars']} Stars за {pkg['ton']} TON</b>\n\n"
        "📝 Введи свой <b>Telegram username</b> куда отправить звёзды:\n\n"
        "Пример: <code>@username</code>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


# ─── Получение username → инвойс ─────────────────────────────────────────────

@dp.message(OrderStates.waiting_username)
async def receive_username(message: Message, state: FSMContext):
    username = message.text.strip()

    # Нормализуем — убираем @ если есть
    if not username.startswith("@"):
        username = "@" + username

    data = await state.get_data()
    pkg_id = data.get("pkg_id")
    pkg = next((p for p in STARS_PACKAGES if p["id"] == pkg_id), None)

    if not pkg:
        await message.answer("❌ Ошибка. Начни заново — /start")
        await state.clear()
        return

    await state.update_data(username=username)

    amount_nanoton = int(pkg["ton"] * 1_000_000_000)
    prices = [LabeledPrice(label=f"⭐ {pkg['stars']} Telegram Stars", amount=amount_nanoton)]

    await message.answer(
        f"✅ Username: <b>{username}</b>\n"
        f"⭐ Пакет: <b>{pkg['stars']} Stars</b>\n"
        f"💎 Цена: <b>{pkg['ton']} TON</b>\n\n"
        "Оплати счёт ниже 👇",
        parse_mode="HTML"
    )

    await bot.send_invoice(
        chat_id=message.chat.id,
        title=f"⭐ {pkg['stars']} Telegram Stars",
        description=f"Покупка {pkg['stars']} Stars для {username} за {pkg['ton']} TON.",
        payload=f"stars_{pkg['id']}_{message.from_user.id}_{username.replace('@','')}",
        provider_token=PROVIDER_TOKEN,
        currency="TON",
        prices=prices,
        start_parameter=f"buy_{pkg['id']}",
        photo_url="https://telegram.org/img/t_logo.png",
        photo_width=100,
        photo_height=100,
        need_name=False,
        need_email=False,
        need_phone_number=False,
        is_flexible=False,
    )
    await state.clear()


# ─── Pre-checkout ─────────────────────────────────────────────────────────────

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


# ─── Успешная оплата ──────────────────────────────────────────────────────────

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    # payload = "stars_{pkg_id}_{user_id}_{username}"
    parts = payload.split("_")

    pkg_id = parts[1] if len(parts) > 1 else "?"
    buyer_username = parts[3] if len(parts) > 3 else "?"

    pkg = next((p for p in STARS_PACKAGES if p["id"] == pkg_id), None)
    stars = pkg["stars"] if pkg else "?"

    buyer = message.from_user
    buyer_name = f"@{buyer.username}" if buyer.username else buyer.full_name

    logger.info(f"✅ Оплата: {buyer.id} | {stars} stars → @{buyer_username} | charge={payment.telegram_payment_charge_id}")

    # ─── Уведомление покупателю ───────────────────────────────────────────────
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Купить ещё", callback_data="buy_stars")

    await message.answer(
        f"✅ <b>Оплата прошла успешно!</b>\n\n"
        f"⭐ <b>{stars} Stars</b> будут отправлены на <b>@{buyer_username}</b>\n"
        f"⏱ Ожидай — обычно до 10 минут\n\n"
        f"🧾 ID транзакции:\n<code>{payment.telegram_payment_charge_id}</code>\n\n"
        f"Спасибо за покупку! 🎉",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

    # ─── Уведомление админу ───────────────────────────────────────────────────
    admin_builder = InlineKeyboardBuilder()
    admin_builder.button(text="✅ Отправлено", callback_data=f"done_{message.from_user.id}_{buyer_username}_{stars}")
    admin_builder.adjust(1)

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🔔 <b>Новый заказ!</b>\n\n"
            f"👤 Покупатель: {buyer_name} (<code>{buyer.id}</code>)\n"
            f"📨 Отправить на: <b>@{buyer_username}</b>\n"
            f"⭐ Количество: <b>{stars} Stars</b>\n"
            f"💎 Сумма: <b>{pkg['ton'] if pkg else '?'} TON</b>\n\n"
            f"🧾 Charge ID: <code>{payment.telegram_payment_charge_id}</code>\n\n"
            f"➡️ Зайди на fragment.com и отправь звёзды на @{buyer_username}"
        ),
        parse_mode="HTML",
        reply_markup=admin_builder.as_markup()
    )


# ─── Админ: кнопка "Отправлено" ───────────────────────────────────────────────

@dp.callback_query(F.data.startswith("done_"))
async def order_done(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    parts = callback.data.split("_")
    buyer_id = int(parts[1]) if len(parts) > 1 else None
    username = parts[2] if len(parts) > 2 else "?"
    stars = parts[3] if len(parts) > 3 else "?"

    # Уведомить покупателя
    if buyer_id:
        try:
            await bot.send_message(
                chat_id=buyer_id,
                text=(
                    f"🎉 <b>Звёзды отправлены!</b>\n\n"
                    f"⭐ <b>{stars} Stars</b> отправлены на @{username}\n\n"
                    f"Спасибо за покупку! Если есть вопросы — /help"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить покупателя {buyer_id}: {e}")

    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ <b>ВЫПОЛНЕНО</b> — уведомление отправлено @{username}",
        parse_mode="HTML"
    )
    await callback.answer("✅ Покупатель уведомлён!")


# ─── /help ────────────────────────────────────────────────────────────────────

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🆘 <b>Помощь</b>\n\n"
        "/start — главное меню\n"
        "/help — эта справка\n\n"
        "По вопросам пиши: @fyhjollyy",
        parse_mode="HTML"
    )


# ─── Запуск ───────────────────────────────────────────────────────────────────

async def main():
    logger.info("🤖 Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
