# Discord Bot - Message Forwarding

Discord бот для пересылки сообщений между каналами с поддержкой от имени бота.

## Features / Возможности

- **Message Forwarding** / Пересылка сообщений между каналами
- **Bot Impersonation** / Поддержка от имени бота
- **GIF Support** / Поддержка GIF из Tenor
- **Slash Commands** / Слэш-команды (/set, /help, /status)
- **Docker Support** / Поддержка Docker
- **Environment Configuration** / Конфигурация через переменные окружения

## Installation & Usage / Установка и использование

### Method 1: Docker (Recommended) / Способ 1: Docker (Рекомендуется)

#### Prerequisites / Требования
- Docker
- Docker Compose

#### Setup / Настройка

1. **Clone the repository** / Клонируйте репозиторий:
```bash
git clone https://github.com/WildFuerry/bot-snd-msg.git
cd bot-snd-msg
```

2. **Create environment file** / Создайте файл окружения:
```bash
# Create .env file
echo "DISCORD_TOKEN=your_discord_token_here" > .env
echo "DISCORD_GUILD_ID=your_guild_id_here" >> .env
```

3. **Create docker-compose.yml** / Создайте docker-compose.yml:
```yaml
version: '3.8'
services:
  discord-bot:
    build: .
    container_name: discord-bot
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./config.json:/app/config.json
      - ./temp:/app/temp
    environment:
      - PYTHONUNBUFFERED=1
```

4. **Run with Docker Compose** / Запустите с Docker Compose:
```bash
docker-compose up -d
```

5. **View logs** / Просмотр логов:
```bash
docker-compose logs -f discord-bot
```

6. **Stop the bot** / Остановка бота:
```bash
docker-compose down
```

### Method 2: Python Direct / Способ 2: Python напрямую

#### Prerequisites / Требования
- Python 3.8+
- pip

#### Setup / Настройка

1. **Clone the repository** / Клонируйте репозиторий:
```bash
git clone https://github.com/WildFuerry/bot-snd-msg.git
cd bot-snd-msg
```

2. **Install dependencies** / Установите зависимости:
```bash
pip install -r requirements.txt
```

3. **Create environment file** / Создайте файл окружения:
```bash
# Create .env file
echo "DISCORD_TOKEN=your_discord_token_here" > .env
echo "DISCORD_GUILD_ID=your_guild_id_here" >> .env
```

4. **Run the bot** / Запустите бота:
```bash
python main.py
```

## Configuration / Конфигурация

### Environment Variables / Переменные окружения

Create a `.env` file in the project root: / Создайте файл `.env` в корне проекта:

```env
DISCORD_TOKEN=your_discord_bot_token
DISCORD_GUILD_ID=your_guild_id
```

### Bot Setup / Настройка бота

1. **Create Discord Application** / Создайте Discord приложение:
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create New Application
   - Go to "Bot" section
   - Copy the token

2. **Invite Bot to Server** / Пригласите бота на сервер:
   - Go to "OAuth2" → "URL Generator"
   - Select scopes: `bot`, `applications.commands`
   - Select permissions: `Send Messages`, `Use Slash Commands`, `Read Message History`
   - Use the generated URL to invite the bot

3. **Get Guild ID** / Получите ID сервера:
   - Enable Developer Mode in Discord
   - Right-click on your server → Copy Server ID

## Bot Commands / Команды бота

### `/set` - Configure forwarding / Настройка пересылки
- Select source channel (канал-источник)
- Select target channel (канал-назначения)
- Bot will forward messages from source to target

### `/help` - Show help / Показать справку
- Displays available commands and usage

### `/status` - Show status / Показать статус
- Shows current forwarding configuration

## File Structure / Структура файлов

```
bot-snd-msg/
├── main.py              # Main bot code / Основной код бота
├── config.json          # Configuration file / Файл конфигурации
├── requirements.txt     # Python dependencies / Python зависимости
├── Dockerfile          # Docker configuration / Docker конфигурация
├── .env                # Environment variables / Переменные окружения
├── .gitignore          # Git ignore rules / Правила игнорирования Git
└── README.md           # This file / Этот файл
```

## Troubleshooting / Устранение неполадок

### Common Issues / Частые проблемы

1. **Bot not responding** / Бот не отвечает:
   - Check if token is correct / Проверьте правильность токена
   - Ensure bot has required permissions / Убедитесь, что у бота есть нужные права

2. **Commands not working** / Команды не работают:
   - Check if bot has `applications.commands` scope / Проверьте scope `applications.commands`
   - Wait for commands to register (may take up to 1 hour) / Подождите регистрации команд (до 1 часа)

3. **Docker issues** / Проблемы с Docker:
   - Check if ports are available / Проверьте доступность портов
   - Ensure Docker daemon is running / Убедитесь, что Docker демон запущен

## Contributing / Вклад в проект

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License / Лицензия

This project is open source and available under the MIT License.

---

**Note**: Make sure to keep your `.env` file secure and never commit it to version control.
**Примечание**: Храните файл `.env` в безопасности и никогда не коммитьте его в систему контроля версий. 