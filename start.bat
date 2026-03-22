@echo off
chcp 65001 > nul
title VPN Telegram Bot
color 0A

echo ================================
echo    Запуск VPN Telegram бота     
echo ================================
echo.

:: Переходим в папку с ботом
cd /d C:\Users\maxig\Desktop\MI_BotTGv1\Bot

:: Проверка наличия Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [31mPython не найден. Установите Python 3.8 или выше[0m
    pause
    exit /b 1
)

:: Проверка версии Python
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set python_version=%%i
echo [92m✓ Найден Python %python_version%[0m

:: Проверка наличия виртуального окружения
if not exist venv (
    echo [93mВиртуальное окружение не найдено. Создаю...[0m
    python -m venv venv
    echo [92m✓ Виртуальное окружение создано[0m
)

:: Активация виртуального окружения
call venv\Scripts\activate.bat

:: Установка зависимостей
echo [93mУстановка зависимостей...[0m
pip install -r requirements.txt

:: Проверка .env файла
if not exist .env (
    echo [93mФайл .env не найден. Создаю из примера...[0m
    copy .env.example .env
    echo [91m⚠️  Отредактируйте файл .env и добавьте ваш BOT_TOKEN[0m
    notepad .env
    pause
    exit /b 1
)

:: Запуск бота
echo [92m✓ Запуск бота...[0m
python main.py

pause