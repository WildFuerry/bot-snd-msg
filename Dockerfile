# Используем официальный Python образ
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt ./

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Создаем пользователя для безопасности
RUN useradd -m -u 1000 botuser

# Создаем директорию для временных файлов с правильными правами
RUN mkdir -p /app/trsh && chmod 775 /app/trsh

# Копируем код приложения
COPY main.py ./

# Устанавливаем владельца для всех файлов и директорий
RUN chown -R botuser:botuser /app

# Переключаемся на пользователя botuser
USER botuser


# Запускаем бота
CMD ["python", "main.py"] 
