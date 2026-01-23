# Используем официальный Python образ
FROM python:3.11-slim

# Устанавливаем gosu для безопасного переключения пользователя
RUN apt-get update && apt-get install -y gosu && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt ./

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Создаем пользователя для безопасности
RUN useradd -m -u 1000 botuser

# Копируем код приложения
COPY main.py ./

# Копируем entrypoint скрипт
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Устанавливаем владельца для всех файлов и директорий
RUN chown -R botuser:botuser /app

# Создаем директорию для временных файлов
RUN mkdir -p /app/trsh

# Устанавливаем entrypoint (запускается от root для установки прав)
ENTRYPOINT ["/entrypoint.sh"]

# Оставляем root для entrypoint, переключение на botuser будет в entrypoint.sh


# Запускаем бота
CMD ["python", "main.py"] 
