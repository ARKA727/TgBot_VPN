#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Главный файл для запуска VPN бота
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Добавляем текущую директорию в путь
sys.path.append(str(Path(__file__).parent))

from bot import main as bot_main
from database import init_db
from config import BOT_TOKEN, check_config

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

async def startup():
    """Действия при запуске бота"""
    logger.info("=" * 50)
    logger.info("Запуск VPN бота")
    logger.info("=" * 50)
    
    # Проверяем конфигурацию
    if not check_config():
        logger.error("Ошибка конфигурации. Бот остановлен.")
        return False
    
    # Инициализируем базу данных
    try:
        init_db()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False
    
    logger.info(f"✅ Токен бота: {BOT_TOKEN[:10]}...")
    logger.info("✅ Бот готов к запуску")
    return True

async def shutdown():
    """Действия при остановке бота"""
    logger.info("🛑 Остановка бота...")
    # Здесь можно добавить сохранение состояния, закрытие соединений и т.д.
    logger.info("✅ Бот остановлен")

async def main():
    """Главная функция запуска"""
    try:
        # Выполняем действия при запуске
        if not await startup():
            return
        
        # Запускаем бота
        await bot_main()
        
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        await shutdown()

if __name__ == "__main__":
    asyncio.run(main())