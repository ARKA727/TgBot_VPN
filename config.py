# -*- coding: utf-8 -*-

import os
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
    DOTENV_LOADED = True
except ImportError:
    DOTENV_LOADED = False

logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "F9D7AAC679CB3E599AF0B75237AD19B58C4E84A7F7FFDC5EEA0BE221356E60E7")

# Настройки базы данных
DATABASE_NAME = os.getenv("DATABASE_NAME", "vpn_bot.db")

# ID администраторов
try:
    admin_ids_str = os.getenv("ADMIN_IDS", "280478260")
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip()]
except:
    ADMIN_IDS = []

# ========== НАСТРОЙКИ ЮМАНИ ==========
YOOMONEY_TOKEN = os.getenv("YOOMONEY_TOKEN", "F9D7AAC679CB3E599AF0B75237AD19B58C4E84A7F7FFDC5EEA0BE221356E60E7")  # OAuth токен
YOOMONEY_WALLET = os.getenv("YOOMONEY_WALLET", "4100119498485026")  # Номер кошелька
YOOMONEY_REDIRECT_URL = os.getenv("YOOMONEY_REDIRECT_URL", "https://t.me/MaxkVPN_bot")  # URL для возврата
# ====================================

# Настройки VPN серверов
VPN_SERVERS = [
    {
        'name': '🇳🇱 Нидерланды',
        'id': 'nl',
        'ip': 'ams.vpn-server.com',
        'location': 'Amsterdam',
        'flag': '🇳🇱'
    },
    {
        'name': '🇩🇪 Германия',
        'id': 'de',
        'ip': 'fra.vpn-server.com',
        'location': 'Frankfurt',
        'flag': '🇩🇪'
    },
    {
        'name': '🇺🇸 США',
        'id': 'us',
        'ip': 'nyc.vpn-server.com',
        'location': 'New York',
        'flag': '🇺🇸'
    },
]

# Тарифные планы
VPN_PLANS = [
    {
        'name': '1 месяц',
        'duration': 30,
        'price_stars': 100,
        'price_rub': 299,  # Цена в рублях для Юмани
        'price_usd': 2.99,
        'popular': False
    },
    {
        'name': '3 месяца',
        'duration': 90,
        'price_stars': 250,
        'price_rub': 699,  # Цена в рублях для Юмани
        'price_usd': 7.99,
        'popular': True,
        'discount': '20%'
    },
    {
        'name': '6 месяцев',
        'duration': 180,
        'price_stars': 450,
        'price_rub': 1199,  # Цена в рублях для Юмани
        'price_usd': 14.99,
        'popular': False,
        'discount': '25%'
    },
    {
        'name': '12 месяцев',
        'duration': 365,
        'price_stars': 800,
        'price_rub': 1999,  # Цена в рублях для Юмани
        'price_usd': 24.99,
        'popular': False,
        'discount': '30%'
    },
]

def check_config():
    """Проверка конфигурации"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
        return False
    
    logger.info(f"✅ Конфигурация проверена успешно")
    logger.info(f"🤖 Бот токен: {BOT_TOKEN[:10]}...")
    
    # Проверка Юмани
    if YOOMONEY_TOKEN:
        logger.info("✅ Юмани токен установлен")
    else:
        logger.warning("⚠️ Юмани токен не установлен - оплата через Юмани недоступна")
    
    return True