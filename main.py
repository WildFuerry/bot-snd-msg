"""
Discord Bot - Пересылка сообщений в Telegram

Основной функционал:
- Пересылка сообщений из исходного Discord канала в целевой канал
- Синхронизация с Telegram: отправка, редактирование, удаление сообщений
- Конвертация форматирования Discord markdown в Telegram HTML
- Обработка медиа-файлов (изображения, видео, GIF, включая Tenor)
- Фильтрация предпросмотров ссылок
- Периодическое открепление сообщений в Telegram

Структура:
- ConfigManager: управление конфигурацией
- MessageHandler: обработка сообщений и работа с Telegram API
- ChannelSelect: UI компонент для выбора канала
- События Discord: on_message, on_message_edit, on_message_delete
- Слэш-команды: /set, /help, /status
"""

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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger('discord').setLevel(logging.WARNING)

CONFIG_FILE = 'config.json'

# Runtime-configured values (initialized in main()).
SOURCE_CHANNEL_ID: Optional[int] = None
CHANNELS: dict[str, int] = {}
TRSH_DIR = 'trsh'


def _parse_int_env(name: str) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        logger.error(f"Некорректное значение переменной окружения {name}: {raw!r} (ожидается число)")
        return None


def _load_channels_from_env() -> Optional[dict]:
    """
    CHANNELS_JSON should be a JSON object: {"новости": 123, "ивент-события": 456}
    """
    raw = os.getenv("CHANNELS_JSON")
    if raw is None or raw.strip() == "":
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Некорректный JSON в CHANNELS_JSON: {e}")
        return None
    if not isinstance(parsed, dict):
        logger.error("CHANNELS_JSON должен быть JSON-объектом (словарём) name->id")
        return None

    result: dict[str, int] = {}
    for k, v in parsed.items():
        if not isinstance(k, str) or not k.strip():
            logger.error("CHANNELS_JSON содержит пустой/некорректный ключ канала")
            return None
        try:
            channel_id = int(v)
        except (TypeError, ValueError):
            logger.error(f"CHANNELS_JSON: id канала для {k!r} должен быть числом, получено: {v!r}")
            return None
        result[k.strip().lower()] = channel_id

    if not result:
        logger.error("CHANNELS_JSON пустой — нужен хотя бы один канал")
        return None
    return result


def init_runtime_config() -> None:
    global SOURCE_CHANNEL_ID, CHANNELS, CONFIG_FILE

    cfg_file = os.getenv('CONFIG_FILE')
    if cfg_file:
        CONFIG_FILE = cfg_file

    # Load from config file (optional) first, then let env override.
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                if SOURCE_CHANNEL_ID is None:
                    src = data.get("source_channel_id")
                    if src is not None:
                        try:
                            SOURCE_CHANNEL_ID = int(src)
                        except (TypeError, ValueError):
                            logger.error(f"config: source_channel_id должен быть числом, получено: {src!r}")
                if not CHANNELS:
                    ch = data.get("channels")
                    if ch is not None:
                        if isinstance(ch, dict):
                            parsed: dict[str, int] = {}
                            for k, v in ch.items():
                                if not isinstance(k, str) or not k.strip():
                                    logger.error("config: channels содержит пустой/некорректный ключ")
                                    parsed = {}
                                    break
                                try:
                                    parsed[k.strip().lower()] = int(v)
                                except (TypeError, ValueError):
                                    logger.error(f"config: channels[{k!r}] должен быть числом, получено: {v!r}")
                                    parsed = {}
                                    break
                            if parsed:
                                CHANNELS = parsed
                        else:
                            logger.error("config: channels должен быть объектом (словарём) name->id")
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка чтения {CONFIG_FILE}: {e}")
        except Exception as e:
            logger.error(f"Ошибка загрузки {CONFIG_FILE}: {e}")

    source_id = _parse_int_env("SOURCE_CHANNEL_ID")
    if source_id is not None:
        SOURCE_CHANNEL_ID = source_id

    channels = _load_channels_from_env()
    if channels is not None:
        CHANNELS = channels


def validate_runtime_config() -> bool:
    ok = True
    if SOURCE_CHANNEL_ID is None:
        logger.error("SOURCE_CHANNEL_ID не задан. Укажите его в .env / переменных окружения.")
        ok = False
    if not CHANNELS:
        logger.error("CHANNELS_JSON не задан или пуст. Укажите словарь каналов в .env / переменных окружения.")
        ok = False
    return ok

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

message_mapping = {}
start_time = None

"""
Управление конфигурацией бота
Хранение и загрузка ID целевого канала для пересылки сообщений
"""
class ConfigManager:
    @staticmethod
    def load_target_channel() -> Optional[int]:
        if not os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump({'target_channel_id': None}, f, indent=2)
            except Exception as e:
                logger.warning(f"Не удалось создать файл конфигурации: {e}")
            return None
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('target_channel_id')
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка чтения конфигурации: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при загрузке конфигурации: {e}")
            return None

    @staticmethod
    def save_target_channel(channel_id: int) -> bool:
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({'target_channel_id': channel_id}, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации: {e}")
            return False

"""
Обработка сообщений: пересылка, редактирование, удаление
Конвертация форматирования Discord -> Telegram HTML
Работа с медиа-файлами и эмбедами
"""
class MessageHandler:
    @staticmethod
    async def download_gif(url: str, filename: str) -> Optional[str]:
        try:
            filepath = os.path.join(TRSH_DIR, filename)
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        with open(filepath, 'wb') as f:
                            f.write(await resp.read())
                        return filepath
                    else:
                        logger.error(f"Не удалось скачать файл: {url}, статус: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Ошибка при скачивании файла: {e}")
            return None

    @staticmethod
    def extract_media_url(embeds: List[discord.Embed]) -> Optional[str]:
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
        filtered_embeds = []
        for embed in embeds:
            has_media = embed.image or embed.video or embed.thumbnail
            if has_media:
                new_embed = discord.Embed()
                if embed.title:
                    new_embed.title = embed.title
                if embed.description:
                    new_embed.description = embed.description
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
                return content
            for m in soup.find_all('meta'):
                c = m.get('content') if isinstance(m, Tag) and m.has_attr('content') else None
                if isinstance(c, str) and c.endswith('.gif'):
                    return c
            gif_links = re.findall(r'https?://[^\s"\']+\.gif', html)
            if gif_links:
                return gif_links[0]
            return None
        except Exception as e:
            logger.error(f"Ошибка при парсинге Tenor: {e}")
            return None

    @staticmethod
    def is_tenor_url(url: str) -> bool:
        return 'tenor.com/view/' in url

    @staticmethod
    def convert_discord_to_telegram_html(content: str) -> str:
        # Конвертирует Discord форматирование в Telegram HTML формат
        # Discord: **bold**, *italic*, `code`, ~~strikethrough~~, ||spoiler||, [text](url)
        # Telegram: <b>bold</b>, <i>italic</i>, <code>code</code>, <s>strikethrough</s>, <span class="tg-spoiler">spoiler</span>
        # Гиперссылки [text](url) конвертируются в <a href="url">text</a>
        if not content:
            return ""
        
        # Экранируем HTML символы сначала
        content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Обрабатываем форматирование в правильном порядке (изнутри наружу)
        # 1. Сначала обрабатываем ссылки [text](url) - конвертируем в HTML гиперссылку
        def replace_link(match):
            link_text = match.group(1).rstrip()  # Убираем пробелы в конце текста ссылки
            link_url = match.group(2)
            # URL в href обычно не требует экранирования, но экранируем кавычки и амперсанды для безопасности
            # Экранируем только специальные символы в URL: & и "
            link_url_escaped = link_url.replace('&', '&amp;').replace('"', '&quot;')
            # Текст ссылки уже экранирован выше (заменены &, <, >)
            return f'<a href="{link_url_escaped}">{link_text}</a>'
        content = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', replace_link, content)
        
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
        """
        Пересылает сообщение из исходного канала в целевой
        
        Процесс:
        1. Сохранение файлов из attachments для Discord и Telegram
        2. Обработка медиа из embeds (включая парсинг Tenor GIF)
        3. Фильтрация embeds (удаление предпросмотров ссылок)
        4. Отправка в Discord канал
        5. Отправка в Telegram с форматированием и ссылкой на канал
        6. Сохранение маппинга для последующего редактирования/удаления
        """
        global message_mapping
        try:
            # Сохранение файлов из attachments
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
            telegram_content = MessageHandler.convert_discord_to_telegram_html(message.content)
            
            sent_message = await target_channel.send(
                content=message.content,
                files=files,
                embeds=filtered_embeds,
                stickers=message.stickers,
                suppress_embeds=True
            )
            
            # Отправка сообщения в Telegram
            # Подготавливаем файлы и форматируем текст с ссылкой на исходный канал
            telegram_message_id = None
            has_media = False
            telegram_bot_token = os.getenv('TELEGRAM_TOKEN')
            telegram_chat_id = os.getenv('TELEGRAM_GROUP_ID')
            
            if telegram_bot_token and telegram_chat_id:
                telegram_files = []
                if media_file and os.path.exists(media_file):
                    telegram_files.append(media_file)
                if saved_files:
                    telegram_files.extend(saved_files)
                
                telegram_text = telegram_content if telegram_content else message.content
                if not telegram_text and filtered_embeds:
                    telegram_text = filtered_embeds[0].description or filtered_embeds[0].title or ""
                
                # Добавляем ссылку на исходный канал в начало сообщения
                channel_name = None
                for name, channel_id in CHANNELS.items():
                    if channel_id == target_channel.id:
                        channel_name = name.upper()
                        break
                
                if channel_name:
                    guild_id = target_channel.guild.id
                    channel_url = f"https://discord.com/channels/{guild_id}/{target_channel.id}"
                    channel_link = f'<a href="{channel_url}">Канал {channel_name}</a>\n\n'
                    telegram_text = channel_link + (telegram_text if telegram_text else "")
                
                telegram_message_id = await MessageHandler.send_telegram_message(
                    telegram_bot_token,
                    telegram_chat_id,
                    telegram_text,
                    parse_mode='HTML',
                    files=telegram_files if telegram_files else None
                )
                
                has_media = bool(telegram_files)
                
                # Очистка временных файлов
                for temp_file in telegram_files:
                    if os.path.exists(temp_file) and temp_file != media_file:
                        try:
                            os.remove(temp_file)
                        except Exception as e:
                            logger.warning(f"Не удалось удалить временный файл: {e}")
            
            for saved_file in saved_files:
                if os.path.exists(saved_file) and saved_file not in (telegram_files if telegram_bot_token and telegram_chat_id else []):
                    try:
                        os.remove(saved_file)
                    except Exception as e:
                        logger.warning(f"Не удалось удалить временный файл: {e}")
            
            message_mapping[message.id] = {
                'discord': sent_message.id,
                'telegram': telegram_message_id,
                'has_media': has_media
            }
            
            if media_file and os.path.exists(media_file):
                try:
                    os.remove(media_file)
                except Exception as e:
                    logger.error(f"Ошибка при удалении временного файла: {e}")
            return sent_message
        except Exception as e:
            logger.error(f"Ошибка при перенаправлении сообщения {message.id}: {e}")
            return None

    @staticmethod
    async def edit_forwarded_message(
        original_message: discord.Message, 
        target_channel: discord.TextChannel
    ) -> bool:
        """
        Редактирует пересланное сообщение в Discord и Telegram
        """
        global message_mapping
        try:
            message_map = message_mapping.get(original_message.id)
            if not message_map:
                logger.warning(f"Нет маппинга для редактирования: {original_message.id}")
                return False
            
            forwarded_message_id = message_map.get('discord') if isinstance(message_map, dict) else message_map
            if not forwarded_message_id:
                logger.warning(f"Нет Discord ID для редактирования: {original_message.id}")
                return False
            
            try:
                sent_message = await target_channel.fetch_message(forwarded_message_id)
            except discord.NotFound:
                logger.warning(f"Сообщение {forwarded_message_id} не найдено, удаляем из маппинга")
                message_mapping.pop(original_message.id, None)
                return False
            
            filtered_embeds = MessageHandler.filter_embeds(original_message.embeds)
            await sent_message.edit(
                content=original_message.content,
                embeds=filtered_embeds
            )
            
            # Редактирование в Telegram
            telegram_message_id = message_map.get('telegram') if isinstance(message_map, dict) else None
            has_media = message_map.get('has_media', False) if isinstance(message_map, dict) else False
            if telegram_message_id:
                telegram_bot_token = os.getenv('TELEGRAM_TOKEN')
                telegram_chat_id = os.getenv('TELEGRAM_GROUP_ID')
                if telegram_bot_token and telegram_chat_id:
                    telegram_content = MessageHandler.convert_discord_to_telegram_html(original_message.content)
                    
                    channel_name = None
                    for name, channel_id in CHANNELS.items():
                        if channel_id == target_channel.id:
                            channel_name = name.upper()
                            break
                    
                    if channel_name:
                        guild_id = target_channel.guild.id
                        channel_url = f"https://discord.com/channels/{guild_id}/{target_channel.id}"
                        channel_link = f'<a href="{channel_url}">Канал {channel_name}</a>\n\n'
                        telegram_text = channel_link + (telegram_content if telegram_content else "")
                    else:
                        telegram_text = telegram_content if telegram_content else ""
                    
                    result = await MessageHandler.edit_telegram_message(
                        telegram_bot_token,
                        telegram_chat_id,
                        telegram_message_id,
                        telegram_text,
                        has_media=has_media
                    )
                    if not result:
                        logger.warning(f"Не удалось отредактировать сообщение в Telegram: {telegram_message_id}")
            
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
        """
        Отправляет сообщение в Telegram через Bot API
        Поддерживает отправку медиа-файлов (фото, видео, GIF, документы)
        Возвращает message_id или None при ошибке
        """
        try:
            if files and len(files) > 0:
                file_path = files[0] if isinstance(files[0], str) else None
                if file_path and os.path.exists(file_path):
                    file_ext = os.path.splitext(file_path)[1].lower()
                    if file_ext == '.gif':
                        method = 'sendAnimation'
                        field_name = 'animation'
                    elif file_ext in ['.jpg', '.jpeg', '.png']:
                        method = 'sendPhoto'
                        field_name = 'photo'
                    elif file_ext in ['.mp4', '.mov', '.avi']:
                        method = 'sendVideo'
                        field_name = 'video'
                    else:
                        method = 'sendDocument'
                        field_name = 'document'
                    
                    url = f"https://api.telegram.org/bot{telegram_bot_token}/{method}"
                    
                    with open(file_path, 'rb') as f:
                        form_data = aiohttp.FormData()
                        form_data.add_field('chat_id', chat_id)
                        form_data.add_field('disable_web_page_preview', 'true')
                        if text:
                            form_data.add_field('caption', text)
                            form_data.add_field('parse_mode', parse_mode)
                        form_data.add_field(field_name, f, filename=os.path.basename(file_path))
                        
                        async with aiohttp.ClientSession() as session:
                            async with session.post(url, data=form_data) as resp:
                                if resp.status == 200:
                                    result = await resp.json()
                                    if result.get('ok'):
                                        return result.get('result', {}).get('message_id')
                                    else:
                                        logger.error(f"Ошибка отправки файла в Telegram: {result.get('description', 'Unknown error')}")
                                        return None
                                else:
                                    logger.error(f"Ошибка при отправке файла в Telegram: статус {resp.status}")
                                    return None
            
            if not text:
                logger.warning("Пустой текст для отправки в Telegram и нет файлов")
                return None
                
            url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
            data = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get('ok'):
                            return result.get('result', {}).get('message_id')
                        else:
                            logger.error(f"Ошибка отправки сообщения в Telegram: {result.get('description', 'Unknown error')}")
                            return None
                    else:
                        try:
                            error_result = await resp.json()
                            error_desc = error_result.get('description', 'Unknown error')
                            logger.error(f"Ошибка при отправке сообщения в Telegram: статус {resp.status}, описание: {error_desc}")
                        except:
                            logger.error(f"Ошибка при отправке сообщения в Telegram: статус {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения в Telegram: {e}")
            return None

    @staticmethod
    async def edit_telegram_message(
        telegram_bot_token: str, 
        chat_id: str, 
        message_id: int, 
        text: str,
        parse_mode: str = 'HTML',
        has_media: bool = False
    ) -> bool:
        """
        Редактирует сообщение в Telegram
        Для сообщений с медиа использует editMessageCaption, для текстовых - editMessageText
        """
        try:
            if has_media:
                url = f"https://api.telegram.org/bot{telegram_bot_token}/editMessageCaption"
                data = {
                    'chat_id': chat_id,
                    'message_id': message_id,
                    'parse_mode': parse_mode,
                    'disable_web_page_preview': True
                }
                if text:
                    data['caption'] = text
            else:
                url = f"https://api.telegram.org/bot{telegram_bot_token}/editMessageText"
                data = {
                    'chat_id': chat_id,
                    'message_id': message_id,
                    'text': text if text else ' ',
                    'parse_mode': parse_mode,
                    'disable_web_page_preview': True
                }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get('ok'):
                            return True
                        else:
                            logger.warning(f"Не удалось отредактировать сообщение в Telegram: {result.get('description', 'Unknown error')}")
                            return False
                    else:
                        logger.warning(f"Ошибка при редактировании сообщения в Telegram: статус {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения в Telegram: {e}")
            return False

    @staticmethod
    async def unpin_telegram_message(telegram_bot_token: str, chat_id: str, message_id: int) -> bool:
        """
        Открепляет сообщение в Telegram (если оно было закреплено)
        Возвращает True даже если сообщение не было закреплено
        """
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
                        return result.get('ok', True)
                    return True
        except Exception as e:
            logger.debug(f"Ошибка при откреплении сообщения в Telegram: {e}")
            return True

    @staticmethod
    async def delete_telegram_message(telegram_bot_token: str, chat_id: str, message_id: int) -> bool:
        """Удаляет сообщение в Telegram через API"""
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
        """
        Удаляет пересланное сообщение в Discord и Telegram
        """
        global message_mapping
        try:
            message_map = message_mapping.get(original_message.id)
            if not message_map:
                logger.warning(f"Нет маппинга для удаления: {original_message.id}")
                return False
            
            success = True
            
            forwarded_discord_id = message_map.get('discord') if isinstance(message_map, dict) else message_map
            if forwarded_discord_id:
                try:
                    sent_message = await target_channel.fetch_message(forwarded_discord_id)
                    await sent_message.delete()
                except discord.NotFound:
                    pass
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения в Discord: {e}")
                    success = False
            
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
            
            message_mapping.pop(original_message.id, None)
            return success
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения {original_message.id}: {e}")
            return False

"""
UI компоненты и команды Discord
"""
class ChannelSelect(ui.View):
    """View для выбора канала через SelectMenu"""
    def __init__(self):
        super().__init__(timeout=30)
        self.value = None
        options = [
            discord.SelectOption(label=name, value=name)
            for name in CHANNELS.keys()
        ]
        self.select = ui.Select(placeholder="Выберите канал", options=options, min_values=1, max_values=1)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        self.value = self.select.values[0]
        await interaction.response.defer()
        self.stop()

async def periodic_unpin_task():
    """
    Фоновая задача для периодического открепления сообщений из Discord в Telegram
    Выполняется раз в час
    """
    while True:
        try:
            await asyncio.sleep(3600)
            
            telegram_bot_token = os.getenv('TELEGRAM_TOKEN')
            telegram_chat_id = os.getenv('TELEGRAM_GROUP_ID')
            
            if not telegram_bot_token or not telegram_chat_id:
                continue
            
            global message_mapping
            for original_id, message_map in message_mapping.items():
                telegram_message_id = message_map.get('telegram') if isinstance(message_map, dict) else None
                if telegram_message_id:
                    await MessageHandler.unpin_telegram_message(
                        telegram_bot_token,
                        telegram_chat_id,
                        telegram_message_id
                    )
        except Exception as e:
            logger.error(f"Ошибка в периодической задаче открепления: {e}", exc_info=True)

"""
События Discord бота
Обработка сообщений, редактирования и удаления
"""
@bot.event
async def on_ready():
    """Событие запуска бота"""
    global start_time
    start_time = datetime.datetime.now()
    logger.info(f'Бот {bot.user} готов к работе!')
    logger.info(f'ID бота: {bot.user.id}')
    logger.info(f'Бот подключен к {len(bot.guilds)} серверам')
    
    try:
        synced = await tree.sync()
        logger.info(f"Синхронизировано {len(synced)} слеш-команд")
    except Exception as e:
        logger.error(f"Ошибка синхронизации команд: {e}", exc_info=True)
    
    bot.loop.create_task(periodic_unpin_task())

@tree.command(
    name="set", 
    description="Установить целевой канал для перенаправления сообщений"
)
async def set_target(interaction: discord.Interaction):
    """
    Команда для выбора целевого канала пересылки
    Важно: defer() вызывается первым для предотвращения таймаута
    """
    try:
        await interaction.response.defer(ephemeral=True)
        
        if interaction.channel_id != SOURCE_CHANNEL_ID:
            await interaction.followup.send("нет доступа к этому каналу!", ephemeral=True)
            return
        
        view = ChannelSelect()
        await interaction.followup.send(
            "Выберите канал для перенаправления:",
            view=view,
            ephemeral=True
        )
        await view.wait()
        
        if view.value is None:
            await interaction.followup.send("Выбор не был сделан.", ephemeral=True)
            return
        
        channel_name = view.value
        channel_id = CHANNELS.get(channel_name.lower())
        if not channel_id:
            await interaction.followup.send(f"Ошибка: канал {channel_name} не найден.", ephemeral=True)
            return
        
        if ConfigManager.save_target_channel(channel_id):
            channel = interaction.client.get_channel(channel_id)
            channel_mention = channel.mention if isinstance(channel, discord.TextChannel) else str(channel_id)
            await interaction.followup.send(f"Сообщения будут перенаправляться в: {channel_mention}")
        else:
            await interaction.followup.send("Ошибка при сохранении конфигурации!", ephemeral=True)
    except Exception as e:
        logger.error(f"Ошибка в команде /set: {e}", exc_info=True)
        try:
            await interaction.followup.send(f"Произошла ошибка: {str(e)}", ephemeral=True)
        except Exception:
            pass

@tree.command(
    name="help",
    description="Показать справку по командам бота"
)
async def help_command(interaction: discord.Interaction):
    """Показывает список доступных команд"""
    try:
        embed = discord.Embed(title="Доступные команды", color=discord.Color.blue())
        embed.add_field(name="/set", value="Выбрать целевой канал для пересылки сообщений", inline=False)
        embed.add_field(name="/help", value="Показать этот список команд", inline=False)
        embed.add_field(name="/status", value="Показать статус бота и текущий целевой канал", inline=False)
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        logger.error(f"Ошибка в команде /help: {e}", exc_info=True)
        try:
            await interaction.response.send_message(f"Произошла ошибка: {str(e)}", ephemeral=True)
        except:
            pass

@tree.command(
    name="status",
    description="Показать статус бота и текущие настройки"
)
async def status_command(interaction: discord.Interaction):
    """Показывает статус бота, аптайм и целевой канал"""
    try:
        embed = discord.Embed(title="📊 Статус бота", color=discord.Color.green())
        status_emoji = "🟢" if bot.is_ready() else "🔴"
        status_text = "Работает исправно" if bot.is_ready() else "Запущен, но есть проблемы"
        embed.add_field(name=f"{status_emoji} Статус", value=status_text, inline=True)
        
        global start_time
        if start_time:
            uptime = datetime.datetime.now() - start_time
            hours = int(uptime.total_seconds() // 3600)
            minutes = int((uptime.total_seconds() % 3600) // 60)
            uptime_str = f"{hours}ч {minutes}м"
        else:
            uptime_str = "Неизвестно"
        embed.add_field(name="⏱️ Время работы", value=uptime_str, inline=True)
        
        target_channel_id = ConfigManager.load_target_channel()
        if target_channel_id:
            target_channel = bot.get_channel(target_channel_id)
            if target_channel and isinstance(target_channel, discord.TextChannel):
                channel_mention = target_channel.mention
            else:
                channel_mention = f"Канал {target_channel_id}"
        else:
            channel_mention = "Не задан"
        embed.add_field(name="🎯 Целевой канал", value=f"{channel_mention}\n", inline=False)
        embed.set_footer(text=f"Запросил: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        logger.error(f"Ошибка в команде /status: {e}", exc_info=True)
        try:
            await interaction.response.send_message(f"Произошла ошибка: {str(e)}", ephemeral=True)
        except:
            pass

@bot.event
async def on_message(message: discord.Message):
    """Обработка новых сообщений в исходном канале"""
    if message.author == bot.user or message.channel.id != SOURCE_CHANNEL_ID:
        return
    
    target_channel_id = ConfigManager.load_target_channel()
    if not target_channel_id:
        return
    
    target_channel = bot.get_channel(target_channel_id)
    if not target_channel or not isinstance(target_channel, discord.TextChannel):
        logger.error(f"Целевой канал {target_channel_id} не найден")
        return
    
    await MessageHandler.forward_message(message, target_channel)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    """Обработка редактирования сообщений в исходном канале"""
    if before.channel.id != SOURCE_CHANNEL_ID:
        return
    
    target_channel_id = ConfigManager.load_target_channel()
    if not target_channel_id:
        return
    
    target_channel = bot.get_channel(target_channel_id)
    if not target_channel or not isinstance(target_channel, discord.TextChannel):
        logger.error(f"Целевой канал {target_channel_id} не найден")
        return
    
    await MessageHandler.edit_forwarded_message(after, target_channel)

@bot.event
async def on_message_delete(message: discord.Message):
    """Обработка удаления сообщений в исходном канале"""
    if message.channel.id != SOURCE_CHANNEL_ID:
        return
    
    target_channel_id = ConfigManager.load_target_channel()
    if not target_channel_id:
        return
    
    target_channel = bot.get_channel(target_channel_id)
    if not target_channel or not isinstance(target_channel, discord.TextChannel):
        logger.error(f"Целевой канал {target_channel_id} не найден")
        return
    
    await MessageHandler.delete_forwarded_message(message, target_channel)

def main():
    """Точка входа: запуск бота"""
    load_dotenv()
    init_runtime_config()
    if not validate_runtime_config():
        return
    token = os.getenv('BOT_TOKEN')
    if not token:
        logger.error("Переменная окружения BOT_TOKEN не задана!")
        return
    bot.run(token)

if __name__ == "__main__":
    main()
