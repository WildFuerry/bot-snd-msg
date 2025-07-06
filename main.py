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
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s'
)
logger = logging.getLogger(__name__)

# --- Конфигурация и основные параметры ---
CONFIG_FILE = 'config.json'  # файл для хранения целевого канала
SOURCE_CHANNEL_ID = 1285328785033400471  # ID исходного канала для пересылки
CHANNELS = {
    'test1': 1390790589653585920,
    'test2': 1390790628807282901,
}
TRSH_DIR = 'trsh'  # папка для временных файлов (например, gif)

# --- Инициализация бота и команд ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

last_message_id = None  # ID последнего пересланного сообщения
start_time = None  # время запуска бота

# --- Класс для работы с конфигом (чтение/запись целевого канала) ---
class ConfigManager:
    @staticmethod
    def load_target_channel() -> Optional[int]:
        # Чтение ID целевого канала из config.json
        if not os.path.exists(CONFIG_FILE):
            logger.info(f"Файл конфигурации {CONFIG_FILE} не найден")
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
        # Оставляет только медиа-эмбеды для пересылки
        filtered_embeds = []
        for embed in embeds:
            new_embed = discord.Embed()
            if embed.title:
                new_embed.title = embed.title
            if embed.description:
                new_embed.description = embed.description
            elif embed.url:
                new_embed.description = embed.url
            if embed.url:
                new_embed.url = embed.url
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
    async def forward_message(message: discord.Message, target_channel: discord.TextChannel) -> Optional[discord.Message]:
        # Пересылает сообщение из исходного канала в целевой
        global last_message_id
        try:
            files = [await attachment.to_file() for attachment in message.attachments]
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
            logger.info(f"Отправляем сообщение:")
            logger.info(f"  - Контент: {message.content}")
            logger.info(f"  - Файлы: {len(files)}")
            logger.info(f"  - Эмбеды: {len(filtered_embeds)}")
            logger.info(f"  - Стикеры: {len(message.stickers)}")
            # Отправляем сообщение в целевой канал
            sent_message = await target_channel.send(
                content=message.content,
                files=files,
                embeds=filtered_embeds,
                stickers=message.stickers,
            )
            last_message_id = sent_message.id
            # Удаляем временный файл, если был скачан
            if media_file and os.path.exists(media_file):
                try:
                    os.remove(media_file)
                    logger.info(f"Удалён временный файл: {media_file}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении временного файла: {e}")
            logger.info(f"Сообщение {message.id} перенаправлено в канал {target_channel.id}")
            return sent_message
        except Exception as e:
            logger.error(f"Ошибка при перенаправлении сообщения {message.id}: {e}")
            return None

    @staticmethod
    async def edit_forwarded_message(
        original_message: discord.Message, 
        target_channel: discord.TextChannel
    ) -> bool:
        # Редактирует последнее пересланное сообщение в целевом канале
        global last_message_id
        try:
            if not last_message_id:
                logger.warning("Нет сохраненного ID сообщения для редактирования")
                return False
            sent_message = await target_channel.fetch_message(last_message_id)
            filtered_embeds = MessageHandler.filter_embeds(original_message.embeds)
            await sent_message.edit(
                content=original_message.content,
                embeds=filtered_embeds
            )
            logger.info(f"Сообщение {original_message.id} отредактировано в канале {target_channel.id}")
            return True
        except discord.NotFound:
            logger.warning(f"Сообщение {last_message_id} не найдено в целевом канале")
            return False
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения {original_message.id}: {e}")
            return False

    @staticmethod
    async def delete_forwarded_message(target_channel: discord.TextChannel) -> bool:
        # Удаляет последнее пересланное сообщение в целевом канале
        global last_message_id
        try:
            if not last_message_id:
                logger.warning("Нет сохраненного ID сообщения для удаления")
                return False
            sent_message = await target_channel.fetch_message(last_message_id)
            await sent_message.delete()
            last_message_id = None
            logger.info(f"Сообщение {last_message_id} удалено из канала {target_channel.id}")
            return True
        except discord.NotFound:
            logger.warning(f"Сообщение {last_message_id} не найдено в целевом канале")
            last_message_id = None
            return False
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")
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
    try:
        synced = await tree.sync()
        logger.info(f"Синхронизировано {len(synced)} слеш-команд")
    except Exception as e:
        logger.error(f"Ошибка синхронизации команд: {e}")

@tree.command(
    name="set", 
    description="Установить целевой канал для перенаправления сообщений"
)
async def set_target(interaction: discord.Interaction):
    # Команда для выбора целевого канала пересылки
    if interaction.channel_id != SOURCE_CHANNEL_ID:
        await interaction.response.send_message(
            "нет доступа к этому каналу!", ephemeral=True
        )
        return
    view = ChannelSelect(interaction)
    await interaction.response.send_message(
        "Выберите канал для перенаправления:",
        view=view,
        ephemeral=True
    )
    timeout = await view.wait()
    if view.value is None:
        await interaction.followup.send("Выбор не был сделан.", ephemeral=True)
        return
    channel_name = view.value
    channel_id = CHANNELS.get(channel_name.lower())
    if not channel_id:
        await interaction.followup.send(
            f"Ошибка: канал {channel_name} не найден.", ephemeral=True
        )
        return
    if ConfigManager.save_target_channel(channel_id):
        channel = interaction.client.get_channel(channel_id)
        channel_mention = channel.mention if isinstance(channel, discord.TextChannel) else str(channel_id)
        await interaction.followup.send(
            f"Сообщения будут перенаправляться в: {channel_mention}"
        )
    else:
        await interaction.followup.send(
            "Ошибка при сохранении конфигурации!", ephemeral=True
        )

@tree.command(
    name="help",
    description="Показать справку по командам бота"
)
async def help_command(interaction: discord.Interaction):
    # Показывает список доступных команд
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

@tree.command(
    name="status",
    description="Показать статус бота и текущие настройки"
)
async def status_command(interaction: discord.Interaction):
    # Показывает статус бота, аптайм и целевой канал
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
    await MessageHandler.delete_forwarded_message(target_channel)

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