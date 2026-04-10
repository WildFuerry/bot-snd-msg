# Используем официальный Python образ
FROM python:3.11-slim

WORKDIR /app

# Копируем зависимости и устанавливаем их (лучше кешируется слоями)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Копируем проект (Dockerfile/README/.github исключаются через .dockerignore при необходимости)
COPY . ./

# Директория для временных файлов должна существовать и быть доступной на запись
RUN mkdir -p /app/trsh \
  && useradd -m -u 1000 botuser \
  && chown -R botuser:botuser /app

ENV PYTHONUNBUFFERED=1

USER botuser
CMD ["python", "main.py"]