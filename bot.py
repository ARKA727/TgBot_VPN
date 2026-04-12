import logging
import asyncio
import config
from datetime import datetime, timedelta
from database import Database
import yoomoney_payment
from subscription_service import provision_after_payment

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.utils.formatting import Text, Bold

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Конфигурация VPN: серверы и тарифы из config (этап 0 — одна панель на EE)
VPN_CONFIG = {
    "servers": [
        {"name": s["name"], "id": s["id"], "ip": s["ip"]} for s in config.VPN_SERVERS
    ],
    "plans": config.VPN_PLANS,
}

# Состояния для FSM
class VPNStates(StatesGroup):
    waiting_for_server = State()
    waiting_for_plan = State()
    waiting_for_payment = State()
    waiting_for_config = State()

db = Database()

# Клавиатуры
def get_main_keyboard(language='ru'):
    builder = ReplyKeyboardBuilder()
    builder.button(text="🛒 Купить подписку")
    builder.button(text="📋 Мои подписки")
    builder.button(text="ℹ️ Помощь")
    builder.button(text="⚙️ Настройки")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_server_keyboard():
    builder = InlineKeyboardBuilder()
    for server in VPN_CONFIG['servers']:
        builder.button(
            text=server['name'],
            callback_data=f"server_{server['id']}"
        )
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def get_plan_keyboard(server_id: str):
    builder = InlineKeyboardBuilder()
    for plan in VPN_CONFIG['plans']:
        builder.button(
            text=f"{plan['name']} - {plan['price_stars']} ⭐",
            callback_data=f"plan_{server_id}_{plan['duration']}_{plan['price_stars']}"
        )
    builder.button(text="🔙 Назад", callback_data="back_to_servers")
    builder.adjust(1)
    return builder.as_markup()

def get_payment_method_keyboard(server_id: str, duration: int, price_stars: int, price_rub: int, plan_name: str):
    """Клавиатура выбора способа оплаты"""
    builder = InlineKeyboardBuilder()
    
    # Кнопка оплаты Stars
    builder.button(
        text=f"💫 Telegram Stars ({price_stars} ⭐)",
        callback_data=f"pay_stars_{server_id}_{duration}_{price_stars}_{plan_name}"
    )
    
    # Кнопка оплаты Юмани
    builder.button(
        text=f"💰 ЮMoney ({price_rub} ₽)",
        callback_data=f"pay_yoomoney_{server_id}_{duration}_{price_rub}_{plan_name}"
    )
    
    builder.button(text="🔙 Назад", callback_data=f"back_to_plans_{server_id}")
    builder.adjust(1)
    
    return builder.as_markup()

# Обработчики команд
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    welcome_text = Text(
        "👋 Привет, ", Bold(user.first_name), "!\n\n",
        "Я бот для продажи VPN-подписок. С моей помощью ты можешь:\n",
        "• 🔒 Получить безопасный доступ к интернету\n",
        "• 🌍 Выбрать сервер в любой стране\n",
        "• ⚡ Высокую скорость соединения\n",
        "• 💳 Удобную оплату через Telegram Stars\n\n",
        "Выбери действие в меню ниже:"
    )
    
    await message.answer(
        **welcome_text.as_kwargs(),
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🛒 Купить подписку")
async def buy_subscription(message: Message):
    text = Text(
        "🌍 Выберите страну для сервера:\n\n",
        "Доступные локации:"
    )
    
    await message.answer(
        **text.as_kwargs(),
        reply_markup=get_server_keyboard()
    )

@dp.message(F.text == "📋 Мои подписки")
async def show_subscriptions(message: Message):
    user_id = message.from_user.id
    subscriptions = db.get_user_subscriptions(user_id)
    
    if not subscriptions:
        await message.answer(
            "📭 У вас пока нет активных подписок.\n"
            "Нажмите '🛒 Купить подписку', чтобы приобрести VPN."
        )
        return
    
    text = "📋 Ваши активные подписки:\n\n"
    
    for sub in subscriptions:
        server_name = next(
            (s['name'] for s in VPN_CONFIG['servers'] if s['id'] == sub['server_id']),
            sub['server_id']
        )
        end_date = datetime.strptime(sub['end_date'], '%Y-%m-%d %H:%M:%S')
        days_left = (end_date - datetime.now()).days
        
        text += f"• {server_name}\n"
        text += f"  Действует до: {end_date.strftime('%d.%m.%Y')}\n"
        text += f"  Осталось дней: {days_left}\n\n"
        
        # Добавляем кнопку для получения конфигурации
        builder = InlineKeyboardBuilder()
        builder.button(
            text="📱 Получить конфигурацию",
            callback_data=f"get_config_{sub['id']}"
        )
        
        await message.answer(text, reply_markup=builder.as_markup())
        text = ""  # Сброс текста для следующего сообщения

@dp.message(F.text == "ℹ️ Помощь")
async def show_help(message: Message):
    help_text = Text(
        "🆘 Помощь по использованию бота:\n\n",
        "❓ Как купить подписку?\n",
        "Нажми '🛒 Купить подписку', выбери страну, тариф и способ оплаты.\n\n",
        
        "❓ Как оплатить Stars?\n",
        "Telegram автоматически обработает платеж через Stars.\n\n",
        
        "❓ Как подключить VPN?\n",
        "После оплаты бот выдаст данные подписки (VLESS через 3x-ui).\n",
        "Импортируй ссылку в v2rayNG, Hiddify, Streisand и т.п.\n\n",
        "❓ Повторная покупка на тот же сервер?\n",
        "Срок продлевается у того же ключа (в панели 3x-ui и в «Мои подписки»).\n\n",
        "❓ Почему VPN иногда отключается в Шортсах (Youtube/insta)?\n"
        "Это связанно с Принципами работы протокла Velness. В этом нет ничего критичного. С большим кол-вом подписчиков будет добавленны новые протоколы.\n\n"
        
        "❓ Есть вопросы?\n",
        "Свяжись с поддержкой: @MXMKGN"
    )
    
    await message.answer(**help_text.as_kwargs())

@dp.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="lang_ru")
    builder.button(text="🇬🇧 English", callback_data="lang_en")
    
    await message.answer(
        "⚙️ Настройки\n\nВыберите язык интерфейса:",
        reply_markup=builder.as_markup()
    )

# Обработчики callback'ов
@dp.callback_query(F.data.startswith("server_"))
async def process_server_selection(callback: CallbackQuery):
    server_id = callback.data.split("_")[1]
    
    await callback.message.edit_text(
        f"✅ Выбран сервер: {server_id.upper()}\n\n"
        "📊 Выберите тарифный план:",
        reply_markup=get_plan_keyboard(server_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("plan_"))
async def process_plan_selection(callback: CallbackQuery, state: FSMContext):
    _, server_id, duration, price_stars = callback.data.split("_")
    duration = int(duration)
    price_stars = int(price_stars)
    
    # Находим план с нужной длительностью
    plan = next(
        (p for p in config.VPN_PLANS if p['duration'] == duration),
        None
    )
    
    if not plan:
        await callback.answer("Ошибка: план не найден")
        return
    
    plan_name = plan['name']
    price_rub = plan['price_rub']
    
    await state.update_data(
        server_id=server_id,
        duration=duration,
        price_stars=price_stars,
        price_rub=price_rub,
        plan_name=plan_name
    )
    
    text = f"""📦 Ваш заказ:

Сервер: {server_id.upper()}
Тариф: {plan_name}
Сумма: {price_stars} ⭐ или {price_rub} ₽

Выберите способ оплаты:"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_payment_method_keyboard(server_id, duration, price_stars, price_rub, plan_name)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_yoomoney_"))
async def process_yoomoney_payment(callback: CallbackQuery, state: FSMContext):
    """Обработка оплаты через Юмани"""
    try:
        _, _, server_id, duration, price_rub, plan_name = callback.data.split("_", 5)
        duration = int(duration)
        price_rub = int(price_rub)
        
        # Создаем уникальный ID платежа
        payment_id = f"yoomoney_{callback.from_user.id}_{int(datetime.now().timestamp())}"
        
        # Сохраняем данные платежа в БД
        db.add_payment(
            user_id=callback.from_user.id,
            amount=price_rub,
            currency="RUB",
            payment_id=payment_id,
            plan_name=plan_name,
            server_id=server_id
        )
        
        # Сохраняем данные в FSM
        await state.update_data(
            pending_payment_id=payment_id,
            server_id=server_id,
            duration=duration,
            plan_name=plan_name
        )
        
        # Создаем платеж в Юмани
        if yoomoney_payment.yoomoney:
            payment_result = await yoomoney_payment.yoomoney.create_payment(
                amount=price_rub,
                description=f"VPN подписка {plan_name}",
                payment_id=payment_id
            )
            
            if payment_result['success']:
                payment_url = payment_result['payment_url']
                
                text = f"""💰 Оплата через ЮMoney

Сумма: {price_rub} ₽
Тариф: {plan_name}
Сервер: {server_id.upper()}

🔗 Ссылка для оплаты: {payment_url}

После оплаты нажмите кнопку ниже для проверки."""

                builder = InlineKeyboardBuilder()
                builder.button(
                    text="✅ Проверить оплату",
                    callback_data=f"check_payment_{payment_id}"
                )
                builder.button(
                    text="🔙 Назад",
                    callback_data="back_to_main"
                )
                builder.adjust(1)
                
                await callback.message.edit_text(
                    text,
                    reply_markup=builder.as_markup(),
                    disable_web_page_preview=True
                )
            else:
                await callback.message.edit_text(
                    "❌ Ошибка при создании платежа. Попробуйте позже.",
                    reply_markup=get_plan_keyboard(server_id)
                )
        else:
            await callback.message.edit_text(
                "❌ Оплата через ЮMoney временно недоступна.",
                reply_markup=get_plan_keyboard(server_id)
            )
            
    except Exception as e:
        logger.error(f"Ошибка в process_yoomoney_payment: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка. Попробуйте позже.",
            reply_markup=get_server_keyboard()
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery, state: FSMContext):
    """Проверка статуса оплаты"""
    payment_id = callback.data.replace("check_payment_", "")
    
    # Получаем данные платежа из БД
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM payments WHERE payment_id = ?",
            (payment_id,)
        )
        payment = cursor.fetchone()
    
    if not payment:
        await callback.answer("❌ Платеж не найден", show_alert=True)
        return
    
    if payment['user_id'] != callback.from_user.id:
        await callback.answer("❌ Это не ваш платёж", show_alert=True)
        return
    
    if payment['status'] == 'completed':
        await callback.answer("✅ Оплата уже подтверждена", show_alert=True)
        return
    
    # Проверяем статус в Юмани
    if payment['currency'] == "RUB" and yoomoney_payment.yoomoney:
        status = await yoomoney_payment.yoomoney.check_payment_status(payment_id)
        
        if not status.get('success'):
            await callback.answer(
                f"⚠️ Не удалось проверить оплату: {status.get('error', 'ошибка API')}",
                show_alert=True,
            )
            return
        
        if status.get('status') == 'not_found':
            await callback.answer(
                "⏳ Платёж пока не найден. Оплатите по ссылке и подождите минуту.",
                show_alert=True,
            )
            return
        
        if status.get('status') == 'pending':
            await callback.answer("⏳ Платёж в обработке, попробуйте позже.", show_alert=True)
            return
        
        if status.get('status') == 'completed':
            db.update_payment_status(payment_id, "completed")

            duration_days = next(
                (p['duration'] for p in config.VPN_PLANS if p['name'] == payment['plan_name']),
                30,
            )
            renew = db.get_active_xui_subscription(
                callback.from_user.id, str(payment["server_id"])
            )
            outcome = await provision_after_payment(
                telegram_user_id=callback.from_user.id,
                server_id=str(payment["server_id"]),
                duration_days=duration_days,
                renew_row=renew,
            )
            if outcome.ok and outcome.config_data:
                if (
                    outcome.was_renewal
                    and outcome.subscription_db_id is not None
                    and outcome.end_date_for_db is not None
                ):
                    db.update_subscription_renewal(
                        outcome.subscription_db_id,
                        outcome.config_data,
                        outcome.end_date_for_db,
                    )
                elif not outcome.was_renewal:
                    db.add_subscription(
                        callback.from_user.id,
                        payment["server_id"],
                        outcome.config_data,
                        duration_days,
                        xui_client_email=outcome.xui_email,
                        xui_client_uuid=outcome.xui_client_uuid,
                        xui_sub_id=outcome.xui_sub_id,
                        xui_inbound_id=outcome.xui_inbound_id,
                    )
                else:
                    logger.error(
                        "Продление без subscription_db_id/end_date, БД не обновлена"
                    )

            await callback.message.edit_text(
                "✅ Оплата подтверждена!\n\n" + outcome.user_message
            )
            await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard())
            await callback.answer()
            return
    
    await callback.answer("❌ ЮMoney недоступен", show_alert=True)

@dp.callback_query(F.data.startswith("pay_stars_"))
async def process_stars_payment(callback: CallbackQuery, state: FSMContext):
    _, _, server_id, duration, price, plan_name = callback.data.split("_", 5)
    duration = int(duration)
    price = int(price)
    
    # Создаем инвойс для оплаты Stars
    prices = [LabeledPrice(label=plan_name, amount=price)]
    
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=f"VPN подписка - {plan_name}",
        description=f"Сервер: {server_id.upper()}\nТариф: {plan_name}",
        payload=f"vpn_{server_id}_{duration}_{plan_name}",
        provider_token="",  # Для Stars оставляем пустым
        currency="XTR",  # Специальная валюта для Stars
        prices=prices,
        start_parameter="vpn_subscription"
    )
    
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message, state: FSMContext):
    payment = message.successful_payment
    user_id = message.from_user.id

    raw = payment.invoice_payload or ""
    if not raw.startswith("vpn_"):
        logger.error("Неожиданный invoice_payload: %s", raw)
        await message.answer("Ошибка данных платежа. Напишите в поддержку: @MXMKGN")
        return
    try:
        _, server_id, duration_str, plan_name = raw.split("_", 3)
        duration = int(duration_str)
    except (ValueError, IndexError):
        logger.exception("Не удалось разобрать payload: %s", raw)
        await message.answer("Ошибка данных платежа. Напишите в поддержку: @MXMKGN")
        return

    # Сохраняем платеж в БД
    payment_id = f"stars_{user_id}_{datetime.now().timestamp()}"
    db.add_payment(
        user_id=user_id,
        amount=payment.total_amount,
        currency="XTR",
        payment_id=payment_id,
        plan_name=plan_name,
        server_id=server_id
    )
    db.update_payment_status(payment_id, "completed")

    renew = db.get_active_xui_subscription(user_id, server_id)
    outcome = await provision_after_payment(
        telegram_user_id=user_id,
        server_id=server_id,
        duration_days=duration,
        renew_row=renew,
    )
    if outcome.ok and outcome.config_data:
        if (
            outcome.was_renewal
            and outcome.subscription_db_id is not None
            and outcome.end_date_for_db is not None
        ):
            db.update_subscription_renewal(
                outcome.subscription_db_id,
                outcome.config_data,
                outcome.end_date_for_db,
            )
        elif not outcome.was_renewal:
            db.add_subscription(
                user_id,
                server_id,
                outcome.config_data,
                duration,
                xui_client_email=outcome.xui_email,
                xui_client_uuid=outcome.xui_client_uuid,
                xui_sub_id=outcome.xui_sub_id,
                xui_inbound_id=outcome.xui_inbound_id,
            )
        else:
            logger.error("Продление без subscription_db_id/end_date, БД не обновлена")

    await message.answer("✅ Оплата прошла успешно!\n\n" + outcome.user_message)

    await message.answer(
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data.startswith("get_config_"))
async def get_config(callback: CallbackQuery):
    sub_id = callback.data.split("_")[2]
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT config_data FROM subscriptions WHERE id = ?",
            (sub_id,)
        )
        result = cursor.fetchone()
    
    if result:
        await callback.message.answer(
            "🔑 Ваши данные подписки:\n\n" + str(result["config_data"]),
            disable_web_page_preview=True,
        )
    else:
        await callback.message.answer("❌ Конфигурация не найдена")
    
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_servers")
async def back_to_servers(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌍 Выберите страну для сервера:",
        reply_markup=get_server_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("back_to_plans_"))
async def back_to_plans(callback: CallbackQuery):
    server_id = callback.data.split("_")[3]
    await callback.message.edit_text(
        f"📊 Выберите тарифный план для сервера {server_id.upper()}:",
        reply_markup=get_plan_keyboard(server_id)
    )
    await callback.answer()

# Запуск бота
async def main():
    logger.info("Запуск бота...")
    config.check_config()
    yoomoney_payment.init_yoomoney()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())