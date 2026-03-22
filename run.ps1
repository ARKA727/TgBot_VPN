# run.ps1
$BotPath = "C:\Users\maxig\Desktop\MI_BotTGv1\Bot"
Set-Location $BotPath

Write-Host "================================" -ForegroundColor Green
Write-Host "   Запуск VPN Telegram бота     " -ForegroundColor Green
Write-Host "   Папка: $BotPath" -ForegroundColor Yellow
Write-Host "================================" -ForegroundColor Green
Write-Host ""

# Проверка наличия Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Найден $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Python не найден. Установите Python 3.8 или выше" -ForegroundColor Red
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

# Проверка наличия виртуального окружения
if (-not (Test-Path "venv")) {
    Write-Host "Виртуальное окружение не найдено. Создаю..." -ForegroundColor Yellow
    python -m venv venv
    Write-Host "✓ Виртуальное окружение создано" -ForegroundColor Green
}

# Активация виртуального окружения
& .\venv\Scripts\Activate.ps1

# Установка зависимостей
Write-Host "Установка зависимостей..." -ForegroundColor Yellow
pip install -r requirements.txt

# Проверка .env файла
if (-not (Test-Path ".env")) {
    Write-Host "Файл .env не найден. Создаю из примера..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "⚠️  Отредактируйте файл .env и добавьте ваш BOT_TOKEN" -ForegroundColor Red
    notepad .env
    Read-Host "Нажмите Enter после редактирования .env файла"
}

# Проверка BOT_TOKEN в .env
$envContent = Get-Content ".env"
$hasToken = $false
foreach ($line in $envContent) {
    if ($line -match "BOT_TOKEN=.+" -and $line -notmatch "your_bot_token_here") {
        $hasToken = $true
        break
    }
}

if (-not $hasToken) {
    Write-Host "⚠️  BOT_TOKEN не установлен в файле .env" -ForegroundColor Red
    Write-Host "Отредактируйте файл .env и добавьте ваш токен" -ForegroundColor Yellow
    notepad .env
    Read-Host "Нажмите Enter для продолжения"
}

# Запуск бота
Write-Host "✓ Запуск бота..." -ForegroundColor Green
Write-Host "Для остановки нажмите Ctrl+C" -ForegroundColor Yellow
Write-Host ""

python main.py

Read-Host "Нажмите Enter для выхода"