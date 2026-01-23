# --- Импорты сторонних и стандартных библиотек ---
import discord
from discord import app_commands
import json
import os
import logging
from typing import Optional, List
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from bs4.element import Tag
import re
from discord import ui
import datetime
from dotenv import load_dotenv

# --- Логирование: выводит инфо и ошибки в консоль ---
logging.basicConfig(
    level=logging.DEBUG,  # Включаем DEBUG для более детального логирования
    format='%(asctime)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s'
)
logger = logging.getLogger(__name__)
# Устанавливаем уровень для discord библиотеки, чтобы не было слишком много логов
logging.getLogger('discord').setLevel(logging.WARNING)

# --- Конфигурация и основные параметры ---
CONFIG_FILE = 'config.json'  # файл для хранения целевого канала
SOURCE_CHANNEL_ID = 1390799684091777134 # ID исходного канала для пересылки
CHANNELS = {
    'новости': 1195304040188358666, 
    'ивент-события': 1196468248603009116,
}
TRSH_DIR = 'trsh'  # папка для временных файлов (например, gif)

# --- Инициализация бота и команд ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Словарь для маппинга исходных сообщений на пересланные
# Структура: {original_message_id: {'discord': forwarded_discord_id, 'telegram': telegram_message_id}}
message_mapping = {}  # Хранит маппинг сообщений для правильного редактирования/удаления
start_time = None  # время запуска бота

# --- Класс для работы с конфигом (чтение/запись целевого канала) ---
class ConfigManager:
    @staticmethod
    def load_target_channel() -> Optional[int]:
        # Чтение ID целевого канала из config.json
        if not os.path.exists(CONFIG_FILE):
            # Создаем файл с пустой структурой при первом запуске
            try:
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump({'target_channel_id': None}, f, indent=2)
                logger.debug(f"Создан файл конфигурации {CONFIG_FILE}")
            except Exception as e:
                logger.warning(f"Не удалось создать файл конфигурации {CONFIG_FILE}: {e}")
            return None
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                target_id = data.get('target_channel_id')
                if target_id:
                    logger.info(f"Загружен целевой канал: {target_id}")
                return target_id
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка чтения {CONFIG_FILE}: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при загрузке конфигурации: {e}")
            return None

    @staticmethod
    def save_target_channel(channel_id: int) -> bool:
        # Сохраняет ID целевого канала в config.json
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({'target_channel_id': channel_id}, f, indent=2)
            logger.info(f"Сохранен целевой канал: {channel_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации: {e}")
            return False

# --- Класс для логики пересылки, редактирования и удаления сообщений ---
class MessageHandler:
    @staticmethod
    async def download_gif(url: str, filename: str) -> Optional[str]:
        # Скачивает gif или медиафайл по url во временную папку
        try:
            filepath = os.path.join(TRSH_DIR, filename)
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        with open(filepath, 'wb') as f:
                            f.write(await resp.read())
                        logger.info(f"GIF скачан: {filepath}")
                        return filepath
                    else:
                        logger.error(f"Не удалось скачать GIF: {url}, статус: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Ошибка при скачивании GIF: {e}")
            return None

    @staticmethod
    def extract_media_url(embeds: List[discord.Embed]) -> Optional[str]:
        # Извлекает ссылку на медиа (gif, mp4, image) из эмбедов
        for embed in embeds:
            if embed.image and embed.image.url:
                return embed.image.url
            if embed.video and embed.video.url:
                return embed.video.url
            if embed.thumbnail and embed.thumbnail.url:
                return embed.thumbnail.url
            if embed.url:
                return embed.url
        return None

    @staticmethod
    def filter_embeds(embeds: List[discord.Embed]) -> List[discord.Embed]:
        # Оставляет только медиа-эмбеды для пересылки (изображения, видео)
        # Исключает ссылочные эмбеды (предпросмотр ссылок)
        filtered_embeds = []
        for embed in embeds:
            # Проверяем, есть ли медиа-контент (изображение, видео, thumbnail)
            has_media = embed.image or embed.video or embed.thumbnail
            
            # Если есть медиа - создаем эмбед только с медиа, без ссылок
            if has_media:
                new_embed = discord.Embed()
                if embed.title:
                    new_embed.title = embed.title
                if embed.description:
                    new_embed.description = embed.description
                # НЕ добавляем embed.url, чтобы убрать предпросмотр ссылок
                if embed.image:
                    new_embed.set_image(url=embed.image.url)
                    filtered_embeds.append(new_embed)
                elif embed.video:
                    if embed.thumbnail:
                        new_embed.set_image(url=embed.thumbnail.url)
                        filtered_embeds.append(new_embed)
                elif embed.thumbnail:
                    new_embed.set_image(url=embed.thumbnail.url)
                    filtered_embeds.append(new_embed)
        return filtered_embeds
    
    @staticmethod
    async def extract_tenor_gif_url(page_url: str) -> Optional[str]:
        # Парсит страницу Tenor для получения прямой ссылки на gif
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(page_url) as resp:
                    if resp.status != 200:
                        logger.error(f"Не удалось получить страницу Tenor: {page_url}, статус: {resp.status}")
                        return None
                    html = await resp.text()
            soup = BeautifulSoup(html, 'html.parser')
            meta = soup.find('meta', property='og:image')
            content = meta.get('content') if isinstance(meta, Tag) and meta.has_attr('content') else None
            if isinstance(content, str) and content.endswith('.gif'):
                logger.info(f"Найдена .gif ссылка через og:image: {content}")
                return content
            for m in soup.find_all('meta'):
                c = m.get('content') if isinstance(m, Tag) and m.has_attr('content') else None
                if isinstance(c, str) and c.endswith('.gif'):
                    logger.info(f"Найдена .gif ссылка через meta: {c}")
                    return c
            gif_links = re.findall(r'https?://[^\s"\']+\.gif', html)
            if gif_links:
                logger.info(f"Найдена .gif ссылка через регулярку: {gif_links[0]}")
                return gif_links[0]
            logger.warning(f".gif ссылка на Tenor не найдена на странице: {page_url}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при парсинге Tenor: {e}")
            return None

    @staticmethod
    def is_tenor_url(url: str) -> bool:
        # Проверяет, является ли ссылка на Tenor gif
        return 'tenor.com/view/' in url

    @staticmethod
    def convert_discord_to_telegram_html(content: str) -> str:
        # Конвертирует Discord форматирование в Telegram HTML формат
        # Discord: **bold**, *italic*, `code`, ~~strikethrough~~, ||spoiler||, [text](url)
        # Telegram: <b>bold</b>, <i>italic</i>, <code>code</code>, <s>strikethrough</s>, <spoiler>spoiler</spoiler>
        # Примечание: убираем гиперссылки - если есть ссылка, отправляем просто текст
        if not content:
            return ""
        
        # Экранируем HTML символы сначала
        content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Обрабатываем форматирование в правильном порядке (изнутри наружу)
        # 1. Сначала обрабатываем ссылки [text](url) - убираем ссылку, оставляем только текст
        def replace_link(match):
            link_text = match.group(1)
            # Убираем пробелы в конце текста ссылки
            return link_text.rstrip()
        content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', replace_link, content)
        
        # 2. Обрабатываем inline code `code` (чтобы не обрабатывать форматирование внутри кода)
        def replace_code(match):
            code_text = match.group(1)
            return f'<code>{code_text}</code>'
        content = re.sub(r'`([^`\n]+)`', replace_code, content)
        
        # 3. Обрабатываем спойлеры ||text|| 
        # Telegram поддерживает спойлеры через <span class="tg-spoiler"> (Bot API 5.6+)
        def replace_spoiler(match):
            spoiler_text = match.group(1)
            return f'<span class="tg-spoiler">{spoiler_text}</span>'
        content = re.sub(r'\|\|([^\|\n]+)\|\|', replace_spoiler, content)
        
        # 4. Обрабатываем strikethrough ~~text~~
        def replace_strike(match):
            strike_text = match.group(1)
            return f'<s>{strike_text}</s>'
        content = re.sub(r'~~([^~\n]+)~~', replace_strike, content)
        
        # 5. Обрабатываем bold **text** или __text__ (двойные символы)
        def replace_bold_double(match):
            bold_text = match.group(1)
            return f'<b>{bold_text}</b>'
        content = re.sub(r'\*\*([^*\n]+)\*\*', replace_bold_double, content)
        content = re.sub(r'__([^_\n]+)__', replace_bold_double, content)
        
        # 6. Обрабатываем italic *text* или _text_ (одиночные символы, но не внутри других тегов)
        def replace_italic(match):
            italic_text = match.group(1)
            return f'<i>{italic_text}</i>'
        # Используем negative lookbehind/lookahead чтобы не обрабатывать * внутри **
        content = re.sub(r'(?<!\*)\*([^*\n<]+)\*(?!\*)', replace_italic, content)
        content = re.sub(r'(?<!_)_([^_\n<]+)_(?!_)', replace_italic, content)
        
        return content

    @staticmethod
    async def forward_message(message: discord.Message, target_channel: discord.TextChannel) -> Optional[discord.Message]:
        # Пересылает сообщение из исходного канала в целевой
        global message_mapping
        try:
            # Сохраняем файлы из attachments для использования в Telegram
            os.makedirs(TRSH_DIR, exist_ok=True)
            saved_files = []  # Пути к сохраненным файлам для Telegram
            files = []
            for attachment in message.attachments:
                # Создаем Discord.File для отправки в Discord
                files.append(await attachment.to_file())
                # Сохраняем файл для Telegram
                try:
                    file_path = os.path.join(TRSH_DIR, attachment.filename)
                    await attachment.save(file_path)
                    saved_files.append(file_path)
                except Exception as e:
                    logger.warning(f"Не удалось сохранить файл {attachment.filename} для Telegram: {e}")
            
            media_url = MessageHandler.extract_media_url(message.embeds)
            media_file = None
            gif_url = None
            # Если это Tenor — парсим страницу для .gif
            if media_url and MessageHandler.is_tenor_url(media_url):
                gif_url = await MessageHandler.extract_tenor_gif_url(media_url)
            # Если нашли .gif — скачиваем и добавляем к файлам
            if gif_url:
                filename = gif_url.split("/")[-1].split("?")[0] or f"{message.id}.gif"
                gif_path = await MessageHandler.download_gif(gif_url, filename)
                if gif_path:
                    files.append(discord.File(gif_path, filename=filename))
                    media_file = gif_path
            # Если не нашли .gif — fallback на обычную медиа-ссылку
            elif media_url:
                filename = media_url.split("/")[-1].split("?")[0] or f"{message.id}.media"
                media_path = await MessageHandler.download_gif(media_url, filename)
                if media_path:
                    files.append(discord.File(media_path, filename=filename))
                    media_file = media_path
            filtered_embeds = MessageHandler.filter_embeds(message.embeds)
            
            # Конвертируем форматирование для Telegram (если нужно отправлять в ТГ)
            # Пока оставляем оригинальный контент для Discord
            telegram_content = MessageHandler.convert_discord_to_telegram_html(message.content)
            
            logger.info(f"Отправляем сообщение:")
            logger.info(f"  - Контент: {message.content}")
            logger.info(f"  - Файлы: {len(files)}")
            logger.info(f"  - Эмбеды: {len(filtered_embeds)}")
            logger.info(f"  - Стикеры: {len(message.stickers)}")
            
            # Отправляем сообщение в целевой канал
            # Используем оригинальный контент для Discord (без HTML форматирования)
            sent_message = await target_channel.send(
                content=message.content,
                files=files,
                embeds=filtered_embeds,
                stickers=message.stickers,
            )
            
            # Отправляем сообщение в Telegram (если настроено)
            telegram_message_id = None
            telegram_bot_token = os.getenv('TELEGRAM_TOKEN')
            telegram_chat_id = os.getenv('TELEGRAM_GROUP_ID')
            
            if telegram_bot_token and telegram_chat_id:
                # Подготавливаем файлы для Telegram (если есть)
                telegram_files = []
                if media_file and os.path.exists(media_file):
                    telegram_files.append(media_file)
                elif saved_files:
                    # Используем уже сохраненные файлы
                    telegram_files = saved_files
                
                # Конвертируем контент в HTML формат для Telegram
                telegram_text = telegram_content if telegram_content else message.content
                if not telegram_text and filtered_embeds:
                    # Если нет текста, но есть эмбеды, берем описание из первого эмбеда
                    telegram_text = filtered_embeds[0].description or filtered_embeds[0].title or ""
                
                # Отправляем в Telegram
                telegram_message_id = await MessageHandler.send_telegram_message(
                    telegram_bot_token,
                    telegram_chat_id,
                    telegram_text,
                    parse_mode='HTML',
                    files=telegram_files if telegram_files else None
                )
                
                # Открепляем сообщение, если оно было автоматически закреплено
                if telegram_message_id:
                    await MessageHandler.unpin_telegram_message(
                        telegram_bot_token,
                        telegram_chat_id,
                        telegram_message_id
                    )
                
                # Удаляем временные файлы, созданные для Telegram
                for temp_file in telegram_files:
                    if os.path.exists(temp_file) and temp_file != media_file:
                        try:
                            os.remove(temp_file)
                        except Exception as e:
                            logger.warning(f"Не удалось удалить временный файл {temp_file}: {e}")
            
            # Удаляем сохраненные файлы из attachments (если они не были использованы в Telegram)
            for saved_file in saved_files:
                if os.path.exists(saved_file) and saved_file not in (telegram_files if telegram_bot_token and telegram_chat_id else []):
                    try:
                        os.remove(saved_file)
                    except Exception as e:
                        logger.warning(f"Не удалось удалить временный файл {saved_file}: {e}")
            
            # Сохраняем маппинг исходного сообщения на пересланное
            # Структура: {original_id: {'discord': discord_id, 'telegram': telegram_id}}
            message_mapping[message.id] = {
                'discord': sent_message.id,
                'telegram': telegram_message_id
            }
            
            # Удаляем временный файл, если был скачан
            if media_file and os.path.exists(media_file):
                try:
                    os.remove(media_file)
                    logger.info(f"Удалён временный файл: {media_file}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении временного файла: {e}")
            logger.info(f"Сообщение {message.id} перенаправлено в канал {target_channel.id} (сохранен маппинг: {message.id} -> {sent_message.id})")
            return sent_message
        except Exception as e:
            logger.error(f"Ошибка при перенаправлении сообщения {message.id}: {e}")
            return None

    @staticmethod
    async def edit_forwarded_message(
        original_message: discord.Message, 
        target_channel: discord.TextChannel
    ) -> bool:
        # Редактирует пересланное сообщение в целевом канале
        global message_mapping
        try:
            # Получаем маппинг сообщения
            message_map = message_mapping.get(original_message.id)
            if not message_map:
                logger.warning(f"Нет сохраненного маппинга для редактирования (исходное: {original_message.id})")
                return False
            
            # Получаем ID пересланного сообщения в Discord
            forwarded_message_id = message_map.get('discord') if isinstance(message_map, dict) else message_map
            if not forwarded_message_id:
                logger.warning(f"Нет сохраненного Discord ID сообщения для редактирования (исходное: {original_message.id})")
                return False
            
            # Пытаемся получить пересланное сообщение
            try:
                sent_message = await target_channel.fetch_message(forwarded_message_id)
            except discord.NotFound:
                logger.warning(f"Пересланное сообщение {forwarded_message_id} не найдено в целевом канале (возможно, было удалено)")
                # Удаляем из маппинга, так как сообщение больше не существует
                message_mapping.pop(original_message.id, None)
                return False
            
            filtered_embeds = MessageHandler.filter_embeds(original_message.embeds)
            await sent_message.edit(
                content=original_message.content,
                embeds=filtered_embeds
            )
            logger.info(f"Сообщение {original_message.id} отредактировано в канале {target_channel.id} (пересланное: {forwarded_message_id})")
            return True
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения {original_message.id}: {e}")
            return False

    @staticmethod
    async def send_telegram_message(
        telegram_bot_token: str, 
        chat_id: str, 
        text: str, 
        parse_mode: str = 'HTML',
        files: Optional[List] = None
    ) -> Optional[int]:
        # Отправляет сообщение в Telegram через Bot API
        # Возвращает message_id отправленного сообщения или None при ошибке
        # Авторизация происходит через токен бота в URL: https://api.telegram.org/bot{token}/method
        try:
            # Если есть файлы, отправляем как фото/документ
            if files and len(files) > 0:
                # Для простоты отправляем только первый файл
                # Можно расширить для отправки нескольких файлов
                file_path = files[0] if isinstance(files[0], str) else None
                if file_path and os.path.exists(file_path):
                    # Определяем тип файла
                    file_ext = os.path.splitext(file_path)[1].lower()
                    if file_ext in ['.jpg', '.jpeg', '.png', '.gif']:
                        method = 'sendPhoto'
                    elif file_ext in ['.mp4', '.mov', '.avi']:
                        method = 'sendVideo'
                    else:
                        method = 'sendDocument'
                    
                    url = f"https://api.telegram.org/bot{telegram_bot_token}/{method}"
                    
                    with open(file_path, 'rb') as f:
                        form_data = aiohttp.FormData()
                        form_data.add_field('chat_id', chat_id)
                        # Если есть текст, добавляем его как caption
                        if text:
                            form_data.add_field('caption', text)
                            form_data.add_field('parse_mode', parse_mode)
                        form_data.add_field('photo' if method == 'sendPhoto' else ('video' if method == 'sendVideo' else 'document'),
                                           f, filename=os.path.basename(file_path))
                        
                        async with aiohttp.ClientSession() as session:
                            async with session.post(url, data=form_data) as resp:
                                if resp.status == 200:
                                    result = await resp.json()
                                    if result.get('ok'):
                                        message_id = result.get('result', {}).get('message_id')
                                        logger.info(f"Файл отправлен в Telegram, message_id: {message_id}")
                                        return message_id
                                    else:
                                        logger.error(f"Ошибка отправки файла в Telegram: {result.get('description', 'Unknown error')}")
                                        return None
                                else:
                                    logger.error(f"Ошибка при отправке файла в Telegram: статус {resp.status}")
                                    return None
            
            # Отправка текстового сообщения (если нет файлов или файлы не отправились)
            if not text:
                logger.warning("Пустой текст для отправки в Telegram и нет файлов")
                return None
                
            url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
            data = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': parse_mode
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as resp:
                    response_text = await resp.text()
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get('ok'):
                            message_id = result.get('result', {}).get('message_id')
                            logger.info(f"Сообщение отправлено в Telegram, message_id: {message_id}")
                            return message_id
                        else:
                            error_desc = result.get('description', 'Unknown error')
                            logger.error(f"Ошибка отправки сообщения в Telegram: {error_desc}")
                            logger.debug(f"Полный ответ Telegram API: {response_text}")
                            return None
                    else:
                        try:
                            error_result = await resp.json()
                            error_desc = error_result.get('description', 'Unknown error')
                            logger.error(f"Ошибка при отправке сообщения в Telegram: статус {resp.status}, описание: {error_desc}")
                            logger.debug(f"Полный ответ Telegram API: {response_text}")
                            logger.debug(f"Отправляемые данные: {data}")
                        except:
                            logger.error(f"Ошибка при отправке сообщения в Telegram: статус {resp.status}")
                            logger.debug(f"Ответ сервера: {response_text}")
                        return None
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения в Telegram: {e}")
            return None

    @staticmethod
    async def unpin_telegram_message(telegram_bot_token: str, chat_id: str, message_id: int) -> bool:
        # Открепляет сообщение в Telegram (если оно было закреплено)
        try:
            url = f"https://api.telegram.org/bot{telegram_bot_token}/unpinChatMessage"
            data = {
                'chat_id': chat_id,
                'message_id': message_id
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get('ok'):
                            logger.debug(f"Сообщение {message_id} откреплено в Telegram чате {chat_id}")
                            return True
                        else:
                            # Если сообщение не было закреплено, это не ошибка
                            logger.debug(f"Сообщение {message_id} не было закреплено или уже откреплено")
                            return True
                    else:
                        # Если сообщение не закреплено, API может вернуть ошибку - это нормально
                        logger.debug(f"Не удалось открепить сообщение {message_id} (возможно, оно не было закреплено)")
                        return True
        except Exception as e:
            logger.debug(f"Ошибка при откреплении сообщения в Telegram: {e}")
            return True  # Не критично, если не удалось открепить

    @staticmethod
    async def delete_telegram_message(telegram_bot_token: str, chat_id: str, message_id: int) -> bool:
        # Удаляет сообщение в Telegram через API
        try:
            url = f"https://api.telegram.org/bot{telegram_bot_token}/deleteMessage"
            data = {
                'chat_id': chat_id,
                'message_id': message_id
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get('ok'):
                            logger.info(f"Сообщение {message_id} удалено из Telegram чата {chat_id}")
                            return True
                        else:
                            logger.warning(f"Не удалось удалить сообщение в Telegram: {result.get('description', 'Unknown error')}")
                            return False
                    else:
                        logger.error(f"Ошибка при удалении сообщения в Telegram: статус {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения в Telegram: {e}")
            return False

    @staticmethod
    async def delete_forwarded_message(
        original_message: discord.Message,
        target_channel: discord.TextChannel
    ) -> bool:
        # Удаляет пересланное сообщение в целевом канале Discord и в Telegram
        global message_mapping
        try:
            # Получаем маппинг сообщения
            message_map = message_mapping.get(original_message.id)
            if not message_map:
                logger.warning(f"Нет сохраненного маппинга для удаления (исходное: {original_message.id})")
                return False
            
            success = True
            
            # Удаляем сообщение в Discord
            forwarded_discord_id = message_map.get('discord') if isinstance(message_map, dict) else message_map
            if forwarded_discord_id:
                try:
                    sent_message = await target_channel.fetch_message(forwarded_discord_id)
                    await sent_message.delete()
                    logger.info(f"Сообщение {forwarded_discord_id} удалено из Discord канала {target_channel.id} (исходное: {original_message.id})")
                except discord.NotFound:
                    logger.warning(f"Пересланное сообщение {forwarded_discord_id} уже удалено в Discord канале")
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения в Discord: {e}")
                    success = False
            
            # Удаляем сообщение в Telegram
            telegram_message_id = message_map.get('telegram') if isinstance(message_map, dict) else None
            if telegram_message_id:
                telegram_bot_token = os.getenv('TELEGRAM_TOKEN')
                telegram_chat_id = os.getenv('TELEGRAM_GROUP_ID')
                if telegram_bot_token and telegram_chat_id:
                    telegram_success = await MessageHandler.delete_telegram_message(
                        telegram_bot_token, 
                        telegram_chat_id, 
                        telegram_message_id
                    )
                    if not telegram_success:
                        success = False
                else:
                    logger.warning("TELEGRAM_TOKEN или TELEGRAM_GROUP_ID не заданы, пропускаем удаление в Telegram")
            
            # Удаляем из маппинга после обработки
            message_mapping.pop(original_message.id, None)
            
            return success
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения {original_message.id}: {e}")
            return False

# --- View для выбора канала через SelectMenu (dropdown) ---
class ChannelSelect(ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=30)
        self.interaction = interaction
        self.value = None
        options = [
            discord.SelectOption(label=name, value=name)
            for name in CHANNELS.keys()
        ]
        self.select = ui.Select(placeholder="Выберите канал", options=options, min_values=1, max_values=1)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        # Сохраняет выбранный канал и завершает выбор
        self.value = self.select.values[0]
        await interaction.response.defer()
        self.stop()

# --- События и команды Discord ---
@bot.event
async def on_ready():
    # Срабатывает при запуске бота
    global start_time
    start_time = datetime.datetime.now()
    logger.info(f'Бот {bot.user} готов к работе!')
    logger.info(f'ID бота: {bot.user.id}')
    logger.info(f'Бот подключен к {len(bot.guilds)} серверам')
    for guild in bot.guilds:
        logger.info(f'  - Сервер: {guild.name} (ID: {guild.id})')
    try:
        synced = await tree.sync()
        logger.info(f"Синхронизировано {len(synced)} слеш-команд")
        for cmd in synced:
            logger.info(f"  - Команда: /{cmd.name} (ID: {cmd.id})")
    except Exception as e:
        logger.error(f"Ошибка синхронизации команд: {e}", exc_info=True)

@bot.event
async def on_interaction(interaction: discord.Interaction):
    # Обработчик всех взаимодействий для отладки
    if interaction.type == discord.InteractionType.application_command:
        command_name = interaction.data.get('name', 'unknown') if hasattr(interaction, 'data') else 'unknown'
        logger.info(f"[INTERACTION] Получено взаимодействие: /{command_name} от {interaction.user} (ID: {interaction.user.id}) в канале {interaction.channel_id}")
        logger.info(f"[INTERACTION] Тип взаимодействия: {interaction.type}, ID: {interaction.id}")

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Глобальный обработчик ошибок для команд
    logger.error(f"Ошибка в команде {interaction.command.name if interaction.command else 'unknown'}: {error}", exc_info=True)
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"Произошла ошибка при выполнении команды: {str(error)}",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"Произошла ошибка при выполнении команды: {str(error)}",
                ephemeral=True
            )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение об ошибке: {e}")

@tree.command(
    name="set", 
    description="Установить целевой канал для перенаправления сообщений"
)
async def set_target(interaction: discord.Interaction):
    # Команда для выбора целевого канала пересылки
    logger.info(f"[COMMAND /set] ========== НАЧАЛО ВЫПОЛНЕНИЯ ==========")
    logger.info(f"[COMMAND /set] Пользователь: {interaction.user} (ID: {interaction.user.id})")
    logger.info(f"[COMMAND /set] Канал: {interaction.channel_id}")
    logger.info(f"[COMMAND /set] SOURCE_CHANNEL_ID: {SOURCE_CHANNEL_ID}")
    logger.info(f"[COMMAND /set] response.is_done(): {interaction.response.is_done()}")
    
    # КРИТИЧНО: Отвечаем немедленно, чтобы Discord не показывал "Приложение не отвечает"
    # Если есть любая задержка до этого момента, Discord покажет ошибку
    try:
        if interaction.channel_id != SOURCE_CHANNEL_ID:
            logger.warning(f"[COMMAND /set] Доступ запрещен: канал {interaction.channel_id} != {SOURCE_CHANNEL_ID}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "нет доступа к этому каналу!", ephemeral=True
                )
            return
        
        logger.info(f"[COMMAND /set] Доступ разрешен, создаем ChannelSelect")
        view = ChannelSelect(interaction)
        logger.info(f"[COMMAND /set] Отправляем сообщение с выбором канала")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Выберите канал для перенаправления:",
                view=view,
                ephemeral=True
            )
        else:
            logger.error(f"[COMMAND /set] КРИТИЧНО: response уже выполнен!")
            await interaction.followup.send(
                "Выберите канал для перенаправления:",
                view=view,
                ephemeral=True
            )
        logger.info(f"[COMMAND /set] Сообщение отправлено, ждем выбора")
        timeout = await view.wait()
        logger.info(f"[COMMAND /set] View завершен, timeout: {timeout}, value: {view.value}")
        if view.value is None:
            logger.warning(f"[COMMAND /set] Выбор не был сделан (timeout или отмена)")
            await interaction.followup.send("Выбор не был сделан.", ephemeral=True)
            return
        channel_name = view.value
        logger.info(f"[COMMAND /set] Выбран канал: {channel_name}")
        channel_id = CHANNELS.get(channel_name.lower())
        if not channel_id:
            logger.error(f"[COMMAND /set] Канал {channel_name} не найден в CHANNELS")
            await interaction.followup.send(
                f"Ошибка: канал {channel_name} не найден.", ephemeral=True
            )
            return
        logger.info(f"[COMMAND /set] ID канала: {channel_id}, сохраняем конфигурацию")
        if ConfigManager.save_target_channel(channel_id):
            channel = interaction.client.get_channel(channel_id)
            channel_mention = channel.mention if isinstance(channel, discord.TextChannel) else str(channel_id)
            logger.info(f"[COMMAND /set] Конфигурация сохранена, отправляем подтверждение")
            await interaction.followup.send(
                f"Сообщения будут перенаправляться в: {channel_mention}"
            )
            logger.info(f"[COMMAND /set] Команда успешно выполнена")
        else:
            logger.error(f"[COMMAND /set] Ошибка при сохранении конфигурации")
            await interaction.followup.send(
                "Ошибка при сохранении конфигурации!", ephemeral=True
            )
    except Exception as e:
        logger.error(f"[COMMAND /set] КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        try:
            if not interaction.response.is_done():
                logger.info(f"[COMMAND /set] Отправляем ошибку через response")
                await interaction.response.send_message(
                    f"Произошла ошибка: {str(e)}",
                    ephemeral=True
                )
            else:
                logger.info(f"[COMMAND /set] Отправляем ошибку через followup")
                await interaction.followup.send(
                    f"Произошла ошибка: {str(e)}",
                    ephemeral=True
                )
        except Exception as send_error:
            logger.error(f"[COMMAND /set] Не удалось отправить сообщение об ошибке: {send_error}", exc_info=True)

@tree.command(
    name="help",
    description="Показать справку по командам бота"
)
async def help_command(interaction: discord.Interaction):
    # Показывает список доступных команд
    logger.info(f"Команда /help вызвана пользователем {interaction.user} в канале {interaction.channel_id}")
    try:
        embed = discord.Embed(
            title="Доступные команды",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="/set",
            value="Выбрать целевой канал для пересылки сообщений",
            inline=False
        )
        embed.add_field(
            name="/help",
            value="Показать этот список команд",
            inline=False
        )
        embed.add_field(
            name="/status",
            value="Показать статус бота и текущий целевой канал",
            inline=False
        )
        await interaction.response.send_message(embed=embed)
        logger.info(f"Команда /help успешно выполнена")
    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /help: {e}", exc_info=True)
        try:
            await interaction.response.send_message(
                f"Произошла ошибка при выполнении команды: {str(e)}",
                ephemeral=True
            )
        except:
            try:
                await interaction.followup.send(
                    f"Произошла ошибка при выполнении команды: {str(e)}",
                    ephemeral=True
                )
            except:
                logger.error("Не удалось отправить сообщение об ошибке")

@tree.command(
    name="status",
    description="Показать статус бота и текущие настройки"
)
async def status_command(interaction: discord.Interaction):
    # Показывает статус бота, аптайм и целевой канал
    logger.info(f"Команда /status вызвана пользователем {interaction.user} в канале {interaction.channel_id}")
    try:
        embed = discord.Embed(
            title="📊 Статус бота",
            color=discord.Color.green()
        )
        status_emoji = "🟢" if bot.is_ready() else "🔴"
        status_text = "Работает исправно" if bot.is_ready() else "Запущен, но есть проблемы"
        embed.add_field(
            name=f"{status_emoji} Статус",
            value=status_text,
            inline=True
        )
        global start_time
        if start_time:
            uptime = datetime.datetime.now() - start_time
            hours = int(uptime.total_seconds() // 3600)
            minutes = int((uptime.total_seconds() % 3600) // 60)
            uptime_str = f"{hours}ч {minutes}м"
        else:
            uptime_str = "Неизвестно"
        embed.add_field(
            name="⏱️ Время работы",
            value=uptime_str,
            inline=True
        )
        target_channel_id = ConfigManager.load_target_channel()
        if target_channel_id:
            target_channel = bot.get_channel(target_channel_id)
            if target_channel and isinstance(target_channel, discord.TextChannel):
                channel_mention = target_channel.mention
                channel_name = target_channel.name
            else:
                channel_mention = f"Канал {target_channel_id}"
                channel_name = "Неизвестен"
        else:
            channel_mention = "Не задан"
            channel_name = "Не задан"
        embed.add_field(
            name="🎯 Целевой канал",
            value=f"{channel_mention}\n",
            inline=False
        )
        embed.set_footer(text=f"Запросил: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
        logger.info(f"Команда /status успешно выполнена")
    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /status: {e}", exc_info=True)
        try:
            await interaction.response.send_message(
                f"Произошла ошибка при выполнении команды: {str(e)}",
                ephemeral=True
            )
        except:
            try:
                await interaction.followup.send(
                    f"Произошла ошибка при выполнении команды: {str(e)}",
                    ephemeral=True
                )
            except:
                logger.error("Не удалось отправить сообщение об ошибке")

@bot.event
async def on_message(message: discord.Message):
    # Обрабатывает новые сообщения в исходном канале
    if message.author == bot.user:
        return
    if message.channel.id != SOURCE_CHANNEL_ID:
        return
    target_channel_id = ConfigManager.load_target_channel()
    if not target_channel_id:
        return
    target_channel = bot.get_channel(target_channel_id)
    if not target_channel or not isinstance(target_channel, discord.TextChannel):
        logger.error(f"Целевой канал {target_channel_id} не найден или не является текстовым каналом!")
        return
    await MessageHandler.forward_message(message, target_channel)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    # Обрабатывает редактирование сообщений в исходном канале
    if before.channel.id != SOURCE_CHANNEL_ID:
        return
    target_channel_id = ConfigManager.load_target_channel()
    if not target_channel_id:
        return
    target_channel = bot.get_channel(target_channel_id)
    if not target_channel or not isinstance(target_channel, discord.TextChannel):
        logger.error(f"Целевой канал {target_channel_id} не найден или не является текстовым каналом!")
        return
    await MessageHandler.edit_forwarded_message(after, target_channel)

@bot.event
async def on_message_delete(message: discord.Message):
    # Обрабатывает удаление сообщений в исходном канале
    if message.channel.id != SOURCE_CHANNEL_ID:
        return
    target_channel_id = ConfigManager.load_target_channel()
    if not target_channel_id:
        return
    target_channel = bot.get_channel(target_channel_id)
    if not target_channel or not isinstance(target_channel, discord.TextChannel):
        logger.error(f"Целевой канал {target_channel_id} не найден или не является текстовым каналом!")
        return
    await MessageHandler.delete_forwarded_message(message, target_channel)

# --- Точка входа: запуск бота ---
def main():
    try:
        load_dotenv()
        logger.info("Запуск Discord бота...")
        token = os.getenv('BOT_TOKEN')
        if not token:
            logger.error("Переменная окружения BOT_TOKEN не задана! Проверьте .env или переменные окружения.")
            return
        bot.run(token)
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")

if __name__ == "__main__":
    main()