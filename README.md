# Discord Bot - Message Forwarding

Discord bot for forwarding messages between channels, with Telegram sync / Discord бот для пересылки сообщений между каналами, с синхронизацией в Telegram

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
- Docker Compose (plugin) / Docker Compose (плагин)

#### Setup / Настройка

This project can be started with Docker in two ways / Этот проект можно запустить через Docker двумя способами:

- **Option A (Code)**: clone this repository and run `docker compose up` / **Вариант A (Код)**: клонируйте репозиторий и запустите в каталоге проекта `docker compose up`
- **Option B (Compose-only)**: download only `docker-compose.yml` (and `.env`) — Compose will build from GitHub / **Вариант B (Только compose)**: скачайте только `docker-compose.yml` (и `.env`) — Compose соберёт образ из GitHub

##### Option A (Code) / Вариант A (Код)

1. **Clone the repository** / Клонируйте репозиторий:
```bash
git clone https://github.com/WildFuerry/bot-snd-msg.git
cd bot-snd-msg
```

2. **Create config file (required)** / Создайте конфиг (обязательно):

Copy `config.example.json` → `config.json` and fill it / Скопируйте `config.example.json` → `config.json` и заполните.

3. **Create environment file** / Создайте файл окружения:
```bash
# Create .env file (example)
echo "BOT_TOKEN=your_discord_token_here" > .env
echo "TELEGRAM_TOKEN=your_telegram_bot_token_here" >> .env
echo "TELEGRAM_GROUP_ID=your_telegram_group_id_here" >> .env
```

4. **Run with Docker Compose** / Запустите с Docker Compose:
```bash
docker compose up -d --build
```

5. **View logs** / Просмотр логов:
```bash
docker compose logs -f bot-send-msg
```

6. **Stop the bot** / Остановка бота:
```bash
docker compose down
```

##### Option B (Compose-only) / Вариант B (Только compose)

1. **Create a folder and download files** / **Создайте папку и скачайте файлы**:
   - `docker-compose.yml`
   - `.env`
   - `config.json` (create from `config.example.json`) / `config.json` (создайте по `config.example.json`)

2. **Fill `config.json` (required)** / **Заполните `config.json` (обязательно)**:

Use `config.example.json` as a template / Возьмите `config.example.json` как шаблон.

3. **Fill `.env`** / **Заполните `.env`**:
```env
BOT_TOKEN=your_discord_token_here
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_GROUP_ID=your_telegram_group_id_here
```

4. **Start** / **Запуск**:
```bash
docker compose up -d --build
```

5. **Logs** / **Логи**:
```bash
docker compose logs -f bot-send-msg
```

Note / Примечание: `docker-compose.yml` builds from GitHub (`build.context` points to the repository). You need internet access on the machine running Docker / `docker-compose.yml` собирает образ из GitHub (через `build.context`), поэтому машине с Docker нужен доступ в интернет.

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
echo "BOT_TOKEN=your_discord_token_here" > .env
echo "TELEGRAM_TOKEN=your_telegram_bot_token_here" >> .env
echo "TELEGRAM_GROUP_ID=your_telegram_group_id_here" >> .env
```

4. **Run the bot** / Запустите бота:
```bash
python main.py
```

## Configuration / Конфигурация

### Environment Variables / Переменные окружения

Create a `.env` file in the project root: / Создайте файл `.env` в корне проекта:

```env
BOT_TOKEN=your_discord_token_here
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_GROUP_ID=your_telegram_group_id_here
```

### Config file / Конфиг-файл

Create `config.json` (you can start from `config.example.json`) / Создайте `config.json` (можно начать с `config.example.json`).

Required fields / Обязательные поля:

- `source_channel_id`: source channel ID / ID исходного канала
- `channels`: map of display name → channel ID / словарь “имя для меню” → ID канала

Optional / Необязательно:

- `target_channel_id`: current selected target channel (also set by `/set`) / текущий целевой канал (также задаётся командой `/set`)

### Bot Setup / Настройка бота

1. **Create Discord Application** / Создайте Discord приложение:
   - Go to [Discord Developer Portal](https://discord.com/developers/applications) / Перейдите на Discord Developer Portal
   - Create New Application / Создайте новое приложение
   - Go to "Bot" section / Перейдите в раздел "Bot"
   - Copy the token / Скопируйте токен

2. **Invite Bot to Server** / Пригласите бота на сервер:
   - Go to "OAuth2" → "URL Generator" / Перейдите в "OAuth2" → "URL Generator"
   - Select scopes: `bot`, `applications.commands` / Выберите области: `bot`, `applications.commands`
   - Select permissions: `Send Messages`, `Use Slash Commands`, `Read Message History` / Выберите разрешения: `Send Messages`, `Use Slash Commands`, `Read Message History`
   - Use the generated URL to invite the bot / Используйте сгенерированную ссылку для приглашения бота

3. **Get Guild ID** / Получите ID сервера:
   - Enable Developer Mode in Discord / Включите режим разработчика в Discord
   - Right-click on your server → Copy Server ID / Щелкните правой кнопкой мыши на вашем сервере → Скопировать ID сервера

## Bot Commands / Команды бота

### `/set` - Configure forwarding / Настройка пересылки
- Select source channel / Выберите канал-источник
- Select target channel / Выберите канал-назначения
- Bot will forward messages from source to target / Бот будет пересылать сообщения из источника в назначение

### `/help` - Show help / Показать справку
- Displays available commands and usage / Отображает доступные команды и их использование

### `/status` - Show status / Показать статус
- Shows bot status, forwarding configuration and uptime / Показывает статус бота, конфигурацию пересылки и время работы

## File Structure / Структура файлов

```
bot-snd-msg/
├── main.py              # Main bot code / Основной код бота
├── config.json          # Configuration file / Файл конфигурации
├── requirements.txt     # Python dependencies / Python зависимости
├── Dockerfile           # Docker configuration / Docker конфигурация
├── .env                 # Environment variables / Переменные окружения
├── .gitignore           # Git ignore rules / Правила игнорирования Git
└── README.md            # This file / Этот файл
```

## Troubleshooting / Устранение неполадок

### Common Issues / Частые проблемы

1. **Bot not responding** / Бот не отвечает:
   - Check if token is correct / Проверьте правильность токена
   - Ensure bot has required permissions / Убедитесь, что у бота есть нужные права

2. **Commands not working** / Команды не работают:
   - Check if bot has `applications.commands` scope / Проверьте область `applications.commands` у бота
   - Wait for commands to register (may take up to 1 hour) / Подождите регистрации команд (до 1 часа)

3. **Docker issues** / Проблемы с Docker:
   - Check if ports are available / Проверьте доступность портов
   - Ensure Docker daemon is running / Убедитесь, что Docker демон запущен

## Releases / Релизы

When you publish a GitHub Release, two extra assets are uploaded automatically / После публикации GitHub Release автоматически добавляются два архива:

- **`bot-snd-msg-source-<tag>.zip`** — Python source only (`main.py`, `requirements.txt`, `README.md`, `config.example.json`, `.gitignore`, `.gitattributes`) / только исходники Python
- **`bot-snd-msg-docker-<tag>.zip`** — Docker bundle (`docker-compose.yml`, `Dockerfile`, `.dockerignore`, `config.example.json`, `README.md`) / отдельный пакет для Docker

The default “Source code” download from GitHub still includes the full tree / стандартная кнопка “Source code” на релизе по-прежнему отдаёт полное дерево репозитория.

## License / Лицензия

This project is open source and available under the MIT License. / Этот проект с открытым исходным кодом и доступен под лицензией MIT.

---

**Note**: Make sure to keep your `.env` file secure and never commit it to version control. / **Примечание**: Храните файл `.env` в безопасности и никогда не коммитьте его в систему контроля версий. 
