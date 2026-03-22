# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы зависимостей
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы бота
COPY . .

# Создаем volume для базы данных и логов
VOLUME ["/app/data", "/app/logs"]

# Запускаем бота
CMD ["python", "main.py"]