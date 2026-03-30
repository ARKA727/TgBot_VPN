import logging
import sqlite3
import asyncio
import config
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from contextlib import contextmanager
from database import Database
from yoomoney_payment import init_yoomoney, yoomoney

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.utils.formatting import Text, Bold
import config

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Конфигурация VPN
VPN_CONFIG = {
    'servers': [
        {'name': '🇳🇱 Нидерланды', 'id': 'nl', 'ip': 'ams.server.com'},
        {'name': '🇩🇪 Германия', 'id': 'de', 'ip': 'fra.server.com'},
    ],
    'plans': [
        {'name': '1 месяц', 'duration': 30, 'price_stars': 100, 'price_usd': 2.99},
        {'name': '3 месяца', 'duration': 90, 'price_stars': 250, 'price_usd': 7.99},
        {'name': '6 месяцев', 'duration': 180, 'price_stars': 450, 'price_usd': 14.99},
        {'name': '12 месяцев', 'duration': 365, 'price_stars': 800, 'price_usd': 24.99},
    ]
}

# Состояния для FSM
class VPNStates(StatesGroup):
    waiting_for_server = State()
    waiting_for_plan = State()
    waiting_for_payment = State()
    waiting_for_config = State()

# Класс для работы с БД
class Database:
    def __init__(self, db_name='vpn_bot.db'):
        self.db_name = db_name
        self.init_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language TEXT DEFAULT 'ru',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица подписок
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    server_id TEXT,
                    config_data TEXT,
                    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_date TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Таблица платежей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    currency TEXT,
                    payment_id TEXT,
                    plan_name TEXT,
                    server_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            conn.commit()

    def add_user(self, user_id, username, first_name, last_name):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name))
            conn.commit()

    def get_user_subscriptions(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM subscriptions 
                WHERE user_id = ? AND is_active = 1 AND end_date > CURRENT_TIMESTAMP
            ''', (user_id,))
            return cursor.fetchall()

    def add_subscription(self, user_id, server_id, config_data, duration_days):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            end_date = datetime.now() + timedelta(days=duration_days)
            cursor.execute('''
                INSERT INTO subscriptions (user_id, server_id, config_data, end_date)
                VALUES (?, ?, ?, ?)
            ''', (user_id, server_id, config_data, end_date))
            conn.commit()
            return cursor.lastrowid

    def add_payment(self, user_id, amount, currency, payment_id, plan_name, server_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO payments (user_id, amount, currency, payment_id, plan_name, server_id, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
            ''', (user_id, amount, currency, payment_id, plan_name, server_id))
            conn.commit()
            return cursor.lastrowid

    def update_payment_status(self, payment_id, status):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE payments SET status = ? WHERE payment_id = ?
            ''', (status, payment_id))
            conn.commit()

# Инициализация БД
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
        "После оплаты ты получишь конфигурационный файл.\n",
        "Используй приложение Outline или любой WireGuard клиент.\n\n",
        
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
        if yoomoney:
            payment_result = await yoomoney.create_payment(
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
    
    # Проверяем статус в Юмани
    if payment['currency'] == "RUB" and yoomoney:
        status = await yoomoney.check_payment_status(payment_id)
        
        if status['status'] == 'completed':
            # Обновляем статус в БД
            db.update_payment_status(payment_id, "completed")
            
            # Генерируем конфигурацию
            config_data = generate_vpn_config(callback.from_user.id, payment['server_id'])
            
            # Создаем подписку
            db.add_subscription(
                callback.from_user.id,
                payment['server_id'],
                config_data,
                next((p['duration'] for p in config.VPN_PLANS if p['name'] == payment['plan_name']), 30)
            )
            
            # Отправляем сообщение об успешной оплате
            await callback.message.edit_text(
                f"""✅ Оплата подтверждена!

                    🔑 Ваша конфигурация VPN:"""
            )

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
    
    # Парсим payload
    payload_parts = payment.invoice_payload.split("_")
    server_id = payload_parts[1]
    duration = int(payload_parts[2])
    plan_name = payload_parts[3]
    
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
    
    # Генерируем конфигурацию (здесь должна быть интеграция с вашей VPN-панелью)
    config_data = generate_vpn_config(user_id, server_id)
    
    # Создаем подписку
    db.add_subscription(user_id, server_id, config_data, duration)
    
    # Отправляем конфигурацию пользователю
    await message.answer(
        "✅ Оплата прошла успешно!\n\n"
        "🔑 Ваша конфигурация VPN:\n"
        f"```\n{config_data}\n```\n\n"
        "📱 Инструкция по подключению:\n"
        "1. Скачайте приложение Outline\n"
        "2. Скопируйте ключ выше\n"
        "3. Добавьте сервер в приложении",
        parse_mode="Markdown"
    )
    
    # Возвращаем в главное меню
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
            f"🔑 Ваша конфигурация:\n```\n{result['config_data']}\n```",
            parse_mode="Markdown"
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

# Вспомогательная функция для генерации конфигурации VPN
def generate_vpn_config(user_id: int, server_id: str) -> str:
    """Генерация конфигурации WireGuard/Outline"""
    # Здесь должна быть реальная генерация ключей через вашу VPN-панель
    # Это пример для демонстрации
    
    server = next((s for s in VPN_CONFIG['servers'] if s['id'] == server_id), None)
    if not server:
        server = VPN_CONFIG['servers'][0]
    
    # Пример конфигурации WireGuard
    config = f"""[Interface]
PrivateKey = <приватный_ключ_клиента>
Address = 10.0.0.{user_id % 255}/24
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = <публичный_ключ_сервера>
Endpoint = {server['ip']}:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""
    return config

# Запуск бота
async def main():
    logger.info("Запуск бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())