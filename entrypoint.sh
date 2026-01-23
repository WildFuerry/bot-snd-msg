#!/bin/bash
# Устанавливаем права на директорию trsh для записи
chmod 777 /app/trsh 2>/dev/null || true
chown -R botuser:botuser /app/trsh 2>/dev/null || true
# Переключаемся на пользователя botuser и запускаем основную команду
exec gosu botuser "$@"
