import discord
from discord.ext import commands
import json
import os
import logging
import asyncio
import re
import time
import uuid
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

# Загружаем токен из .env
load_dotenv()

# ===== НАСТРОЙКИ =====
OWNER_ID = 1490373029102882817
TRUSTED_IDS = [1490373029102882817, 1490372335415328778]
DATA_FILE = 'data.json'
TOKEN = os.getenv('DISCORD_TOKEN')
LOG_CHANNEL_NAME = "logs"  # Название канала для логов

# Настройки варнов
WARNS_BEFORE_BAN = 5  # Общий лимит варнов до бана
WARN_EXPIRE_HOURS = 24

# Настройки анти-спама
SPAM_LIMIT = 5  # Количество сообщений для срабатывания
SPAM_WINDOW = 5  # Окно в секундах
SPAM_ACTION = "warn"
SPAM_MUTE_DURATION = 60
SPAM_WARNS_BEFORE_BAN = 3  # Лимит варнов за спам до бана

# Проверка токена
if not TOKEN:
    print("❌ ОШИБКА: Токен не найден!")
    print("Создайте файл .env с содержимым: DISCORD_TOKEN=ваш_токен")
    exit(1)

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ =====
INVITE_REGEX = re.compile(r'(?:discord\.gg|discord\.com/invite|d\s*i\s*s\s*c\s*o\s*r\s*d)', re.IGNORECASE)
ZALGO_REGEX = re.compile(r'[\u0300-\u036F\u0483-\u0489\u1DC0-\u1DFF\u20D0-\u20FF\u2DE0-\u2DFF\uA640-\uA69F\uFE20-\uFE2F]')

# ===== ДАННЫЕ =====
default_data = {
    "trusted": TRUSTED_IDS,
    "banwords": [],
    "backups": {},
    "warns": {},
    "spam_warns": {},  # Отдельный счетчик варнов за спам
    "muted": {},
    "stats": {
        "preventive_bans": 0,
        "total_bans": 0,
        "deleted_channels": 0,
        "deleted_messages": 0,
        "total_raids": 0,
        "total_warns": 0,
        "total_spam_actions": 0,
        "spam_bans": 0  # Счетчик банов за спам
    },
    "raid_mode": False
}

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(default_data)
        return default_data.copy()
    
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if "warns" not in data:
                data["warns"] = {}
            if "spam_warns" not in data:
                data["spam_warns"] = {}
            if "muted" not in data:
                data["muted"] = {}
            if "total_warns" not in data.get("stats", {}):
                if "stats" not in data:
                    data["stats"] = {}
                data["stats"]["total_warns"] = 0
            if "total_spam_actions" not in data.get("stats", {}):
                data["stats"]["total_spam_actions"] = 0
            if "spam_bans" not in data.get("stats", {}):
                data["stats"]["spam_bans"] = 0
            return data
    except:
        return default_data.copy()

def save_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения: {e}")
        return False

db = load_data()
message_tracker = defaultdict(list)

# ===== ГЛОБАЛЬНАЯ ПЕРЕМЕННАЯ ДЛЯ КАНАЛА ЛОГОВ =====
log_channel_cache = {}

async def get_log_channel(guild):
    """Находит или создает канал для логов с кэшированием"""
    if guild is None:
        return None
    
    # Проверяем кэш
    if guild.id in log_channel_cache:
        channel = log_channel_cache[guild.id]
        # Проверяем что канал еще существует
        try:
            await channel.send("✅")  # Проверка что канал работает
            return channel
        except:
            del log_channel_cache[guild.id]
    
    # Ищем существующий канал
    log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    
    if not log_channel:
        try:
            # Создаем канал
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True)
            }
            
            for role in guild.roles:
                if role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            log_channel = await guild.create_text_channel(
                LOG_CHANNEL_NAME,
                overwrites=overwrites,
                reason="Создание канала для логов бота"
            )
            
            await log_channel.send("📋 **Канал логов создан!**\nСюда будут отправляться все действия бота.")
            print(f"✅ Создан канал логов на сервере {guild.name}")
        except Exception as e:
            print(f"❌ Ошибка создания канала логов: {e}")
            return None
    
    # Сохраняем в кэш
    log_channel_cache[guild.id] = log_channel
    return log_channel

async def send_log(guild, embed):
    """Отправляет лог в канал логов"""
    if guild is None:
        print("❌ guild is None")
        return
    
    try:
        log_channel = await get_log_channel(guild)
        if log_channel:
            await log_channel.send(embed=embed)
            print(f"✅ Лог отправлен в #{LOG_CHANNEL_NAME}")
        else:
            print(f"❌ Не удалось получить канал логов")
    except Exception as e:
        print(f"❌ Ошибка отправки лога: {e}")

# ===== ФУНКЦИИ =====
def clean_old_warns(user_id):
    """Очищает старые предупреждения (общие)"""
    user_id_str = str(user_id)
    if user_id_str not in db.get("warns", {}):
        return
    
    current_time = time.time()
    old_warns = db["warns"][user_id_str]
    fresh_warns = [w for w in old_warns if current_time - w.get("time", 0) < WARN_EXPIRE_HOURS * 3600]
    
    if len(fresh_warns) != len(old_warns):
        db["warns"][user_id_str] = fresh_warns
        save_data(db)

def clean_old_spam_warns(user_id):
    """Очищает старые предупреждения за спам"""
    user_id_str = str(user_id)
    if user_id_str not in db.get("spam_warns", {}):
        return
    
    current_time = time.time()
    old_warns = db["spam_warns"][user_id_str]
    fresh_warns = [w for w in old_warns if current_time - w.get("time", 0) < WARN_EXPIRE_HOURS * 3600]
    
    if len(fresh_warns) != len(old_warns):
        db["spam_warns"][user_id_str] = fresh_warns
        save_data(db)

async def add_warn(user, reason, message_content=""):
    """Добавляет общее предупреждение"""
    if user is None:
        return 0, False
    
    user_id_str = str(user.id)
    clean_old_warns(user.id)
    
    warn_data = {
        "reason": reason,
        "time": time.time(),
        "message": message_content[:100] if message_content else ""
    }
    
    if user_id_str not in db.get("warns", {}):
        db["warns"][user_id_str] = []
    
    db["warns"][user_id_str].append(warn_data)
    db["stats"]["total_warns"] = db["stats"].get("total_warns", 0) + 1
    save_data(db)
    
    warn_count = len(db["warns"][user_id_str])
    
    try:
        await user.send(f"⚠️ **Вы получили предупреждение!**\nПричина: {reason}\nВарнов: {warn_count}/{WARNS_BEFORE_BAN}")
    except:
        pass
    
    return warn_count, warn_count >= WARNS_BEFORE_BAN

async def add_spam_warn(user, reason, message_content=""):
    """Добавляет предупреждение за спам (отдельная система)"""
    if user is None:
        return 0, False
    
    user_id_str = str(user.id)
    clean_old_spam_warns(user.id)
    
    warn_data = {
        "reason": reason,
        "time": time.time(),
        "message": message_content[:100] if message_content else ""
    }
    
    if user_id_str not in db.get("spam_warns", {}):
        db["spam_warns"][user_id_str] = []
    
    db["spam_warns"][user_id_str].append(warn_data)
    db["stats"]["total_spam_actions"] = db["stats"].get("total_spam_actions", 0) + 1
    save_data(db)
    
    spam_warn_count = len(db["spam_warns"][user_id_str])
    
    try:
        await user.send(f"⚠️ **Предупреждение за спам!**\nПричина: {reason}\nВарнов за спам: {spam_warn_count}/{SPAM_WARNS_BEFORE_BAN}")
    except:
        pass
    
    return spam_warn_count, spam_warn_count >= SPAM_WARNS_BEFORE_BAN

async def handle_spam(message):
    """Обработчик спама - выдает варн если много сообщений за 5 секунд"""
    author_id = message.author.id
    current_time = time.time()
    
    # Добавляем сообщение в трекер
    message_tracker[author_id].append(current_time)
    
    # Удаляем сообщения старше SPAM_WINDOW секунд
    message_tracker[author_id] = [t for t in message_tracker[author_id] 
                                  if current_time - t <= SPAM_WINDOW]
    
    # Если сообщений больше или равно лимиту - это спам
    if len(message_tracker[author_id]) >= SPAM_LIMIT:
        # Очищаем трекер для этого пользователя
        message_tracker[author_id] = []
        
        # Удаляем последнее сообщение
        try:
            await message.delete()
            db["stats"]["deleted_messages"] = db["stats"].get("deleted_messages", 0) + 1
        except:
            pass
        
        # Сразу выдаем варн за спам
        spam_warn_count, should_ban = await add_spam_warn(
            message.author, 
            f"Спам: {SPAM_LIMIT}+ сообщений за {SPAM_WINDOW} секунд", 
            message.content
        )
        
        # Отправляем лог о спаме
        embed = discord.Embed(
            title="🚫 ОБНАРУЖЕН СПАМ",
            description=f"Пользователь отправил {SPAM_LIMIT}+ сообщений за {SPAM_WINDOW} секунд",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Пользователь", value=f"{message.author.mention} ({message.author})", inline=False)
        embed.add_field(name="Канал", value=message.channel.mention, inline=True)
        embed.add_field(name="Варнов за спам", value=f"{spam_warn_count}/{SPAM_WARNS_BEFORE_BAN}", inline=True)
        embed.add_field(name="Последнее сообщение", value=message.content[:200] if message.content else "Нет текста", inline=False)
        embed.set_footer(text=f"ID: {message.author.id}")
        
        await send_log(message.guild, embed)
        
        # Проверяем, не пора ли банить
        if should_ban:
            try:
                await message.author.ban(reason=f"Превышение лимита предупреждений за спам ({SPAM_WARNS_BEFORE_BAN})")
                db["stats"]["total_bans"] = db["stats"].get("total_bans", 0) + 1
                db["stats"]["spam_bans"] = db["stats"].get("spam_bans", 0) + 1
                save_data(db)
                
                # Лог о бане за спам
                embed2 = discord.Embed(
                    title="🔨 ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН ЗА СПАМ",
                    description=f"Пользователь получил {SPAM_WARNS_BEFORE_BAN} предупреждений за спам",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed2.add_field(name="Пользователь", value=f"{message.author.mention} ({message.author})", inline=False)
                embed2.add_field(name="Причина", value=f"Систематический спам ({SPAM_WARNS_BEFORE_BAN} нарушений)", inline=False)
                
                await send_log(message.guild, embed2)
                await message.channel.send(f"🔨 {message.author.mention} забанен за систематический спам!")
                
            except Exception as e:
                print(f"Ошибка бана за спам: {e}")
        else:
            # Предупреждаем в чате
            remaining = SPAM_WARNS_BEFORE_BAN - spam_warn_count
            await message.channel.send(
                f"{message.author.mention} ⚠️ **Обнаружен спам! Не спамь!**\n"
                f"Варнов за спам: {spam_warn_count}/{SPAM_WARNS_BEFORE_BAN} (до бана осталось {remaining})",
                delete_after=10
            )
        
        return True  # Был спам
    
    return False  # Спама не было

# ===== БОТ =====
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"✅ Бот {bot.user} успешно запущен!")
    print(f"📊 Защищает сервер от рейдов и спама")
    print(f"⚙️ Настройки спама: {SPAM_LIMIT} сообщений за {SPAM_WINDOW} секунд = варн")
    print(f"⚙️ Варнов за спам до бана: {SPAM_WARNS_BEFORE_BAN}")
    
    # Создаем каналы логов на всех серверах
    for guild in bot.guilds:
        channel = await get_log_channel(guild)
        if channel:
            print(f"📋 Канал логов #{LOG_CHANNEL_NAME} на сервере {guild.name} готов")
        
        # Отправляем приветственное сообщение
        embed = discord.Embed(
            title="🛡️ Бот анти-рейд запущен",
            description="Бот начал работу и будет логировать все действия здесь",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Общие варны до бана", value=str(WARNS_BEFORE_BAN), inline=True)
        embed.add_field(name="Спам варны до бана", value=str(SPAM_WARNS_BEFORE_BAN), inline=True)
        embed.add_field(name="Детектор спама", value=f"{SPAM_LIMIT} сообщений за {SPAM_WINDOW}с", inline=True)
        await send_log(guild, embed)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        await bot.process_commands(message)
        return
    
    if message.guild is None:
        await bot.process_commands(message)
        return
    
    # Игнорируем доверенных и администраторов
    if message.author.id in db.get("trusted", []) or message.author.guild_permissions.administrator:
        await bot.process_commands(message)
        return
    
    content = message.content.lower()
    reason = None
    deleted = False
    
    # Проверка на спам (если спам - сразу выдаем варн)
    is_spam = await handle_spam(message)
    if is_spam:
        await bot.process_commands(message)
        return
    
    # Проверка на банворды
    for word in db.get("banwords", []):
        if word.lower() in content:
            try:
                await message.delete()
                deleted = True
                reason = f"Использование запрещенного слова: {word}"
                db["stats"]["deleted_messages"] = db["stats"].get("deleted_messages", 0) + 1
                save_data(db)
                print(f"🗑 Удалено сообщение от {message.author}: {reason}")
            except Exception as e:
                print(f"Ошибка удаления: {e}")
            break
    
    # Если сообщение было удалено - добавляем варн и отправляем лог
    if deleted and reason:
        warn_count, should_ban = await add_warn(message.author, reason, message.content)
        
        # Отправляем лог в канал
        embed = discord.Embed(
            title="⚠️ НАРУШЕНИЕ",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Пользователь", value=f"{message.author.mention} ({message.author})", inline=False)
        embed.add_field(name="Нарушение", value=reason, inline=False)
        embed.add_field(name="Сообщение", value=message.content[:200] if message.content else "Нет текста", inline=False)
        embed.add_field(name="Общих варнов", value=f"{warn_count}/{WARNS_BEFORE_BAN}", inline=True)
        embed.set_footer(text=f"ID: {message.author.id}")
        
        await send_log(message.guild, embed)
        
        if should_ban:
            try:
                await message.author.ban(reason=f"Превышение лимита предупреждений ({WARNS_BEFORE_BAN})")
                db["stats"]["total_bans"] = db["stats"].get("total_bans", 0) + 1
                save_data(db)
                
                # Лог о бане
                embed2 = discord.Embed(
                    title="🔨 ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed2.add_field(name="Пользователь", value=f"{message.author.mention} ({message.author})", inline=False)
                embed2.add_field(name="Причина", value=f"Получил {WARNS_BEFORE_BAN} предупреждений", inline=False)
                
                await send_log(message.guild, embed2)
                await message.channel.send(f"🔨 {message.author.mention} забанен за превышение {WARNS_BEFORE_BAN} варнов!")
                
            except Exception as e:
                print(f"Ошибка бана: {e}")
        else:
            remaining = WARNS_BEFORE_BAN - warn_count
            await message.channel.send(
                f"{message.author.mention} ⚠️ **Нарушение!** {reason}\nВарнов: {warn_count}/{WARNS_BEFORE_BAN} (осталось {remaining})",
                delete_after=10
            )
    
    await bot.process_commands(message)

@bot.event
async def on_member_ban(guild, user):
    """Логирует баны"""
    embed = discord.Embed(
        title="🔨 ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Пользователь", value=f"{user.mention} ({user})", inline=False)
    embed.add_field(name="ID", value=user.id, inline=False)
    await send_log(guild, embed)

@bot.event
async def on_member_join(member):
    if member.id in db.get("trusted", []):
        return
    
    if member.bot:
        try:
            await member.ban(reason="Антирейд: блокировка подозрительного бота")
            db["stats"]["preventive_bans"] = db["stats"].get("preventive_bans", 0) + 1
            db["stats"]["total_bans"] = db["stats"].get("total_bans", 0) + 1
            save_data(db)
            
            embed = discord.Embed(
                title="🤖 ЗАБЛОКИРОВАН ПОДОЗРИТЕЛЬНЫЙ БОТ",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Бот", value=member.name, inline=False)
            embed.add_field(name="ID", value=member.id, inline=False)
            await send_log(member.guild, embed)
        except:
            pass

# ===== КОМАНДЫ =====

@bot.command()
async def status(ctx):
    embed = discord.Embed(title="🛡️ Статус анти-рейд бота", color=discord.Color.green())
    embed.add_field(name="Рейд-режим", value="🔴 ВКЛ" if db.get("raid_mode") else "🟢 ВЫКЛ", inline=True)
    embed.add_field(name="Забанено всего", value=db["stats"].get("total_bans", 0), inline=True)
    embed.add_field(name="Забанено за спам", value=db["stats"].get("spam_bans", 0), inline=True)
    embed.add_field(name="Выдано общих варнов", value=db["stats"].get("total_warns", 0), inline=True)
    embed.add_field(name="Выдано спам-варнов", value=db["stats"].get("total_spam_actions", 0), inline=True)
    embed.add_field(name="Удалено сообщений", value=db["stats"].get("deleted_messages", 0), inline=True)
    embed.add_field(name="Доверенных", value=len(db.get("trusted", [])), inline=True)
    embed.add_field(name="📋 Канал логов", value=f"#{LOG_CHANNEL_NAME}", inline=True)
    embed.add_field(name="⚙️ Детектор спама", value=f"{SPAM_LIMIT} сообщений за {SPAM_WINDOW}с", inline=False)
    embed.add_field(name="⚙️ Варны до бана", value=f"Общие: {WARNS_BEFORE_BAN} | Спам: {SPAM_WARNS_BEFORE_BAN}", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def warns(ctx, user: discord.User = None):
    target = user or ctx.author
    user_id_str = str(target.id)
    clean_old_warns(target.id)
    clean_old_spam_warns(target.id)
    
    # Создаем embed
    embed = discord.Embed(title=f"⚠️ Предупреждения {target.name}", color=discord.Color.orange())
    
    # Общие варны
    general_warns = db.get("warns", {}).get(user_id_str, [])
    embed.add_field(name="📋 Общие варны", value=f"{len(general_warns)}/{WARNS_BEFORE_BAN}", inline=False)
    
    if general_warns:
        for i, warn in enumerate(general_warns[-3:], 1):
            warn_time = datetime.fromtimestamp(warn.get("time", 0)).strftime("%d.%m.%Y %H:%M")
            embed.add_field(
                name=f"Общий варн #{i}", 
                value=f"Причина: {warn.get('reason', 'Не указана')}\nВремя: {warn_time}", 
                inline=False
            )
    
    # Спам варны
    spam_warns = db.get("spam_warns", {}).get(user_id_str, [])
    embed.add_field(name="🚫 Варны за спам", value=f"{len(spam_warns)}/{SPAM_WARNS_BEFORE_BAN}", inline=False)
    
    if spam_warns:
        for i, warn in enumerate(spam_warns[-3:], 1):
            warn_time = datetime.fromtimestamp(warn.get("time", 0)).strftime("%d.%m.%Y %H:%M")
            embed.add_field(
                name=f"Спам-варн #{i}", 
                value=f"Причина: {warn.get('reason', 'Не указана')}\nВремя: {warn_time}", 
                inline=False
            )
    
    if not general_warns and not spam_warns:
        embed.description = "✅ Нет предупреждений"
    
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def clearwarns(ctx, user: discord.User):
    user_id_str = str(user.id)
    cleared = False
    
    if user_id_str in db.get("warns", {}):
        del db["warns"][user_id_str]
        cleared = True
    
    if user_id_str in db.get("spam_warns", {}):
        del db["spam_warns"][user_id_str]
        cleared = True
    
    if cleared:
        save_data(db)
        await ctx.send(f"✅ Очищены все предупреждения для {user.mention} (общие и за спам)")
    else:
        await ctx.send(f"❌ У {user.mention} нет предупреждений")

@bot.command()
@commands.has_permissions(administrator=True)
async def clearspamwarns(ctx, user: discord.User):
    """Очищает только предупреждения за спам"""
    user_id_str = str(user.id)
    
    if user_id_str in db.get("spam_warns", {}):
        del db["spam_warns"][user_id_str]
        save_data(db)
        await ctx.send(f"✅ Очищены предупреждения за спам для {user.mention}")
    else:
        await ctx.send(f"❌ У {user.mention} нет предупреждений за спам")

@bot.command()
@commands.has_permissions(administrator=True)
async def spamconfig(ctx, limit: int = None, window: int = None):
    """Настройка анти-спама: !spamconfig [лимит] [окно_в_секундах]"""
    global SPAM_LIMIT, SPAM_WINDOW
    
    if limit is None and window is None:
        await ctx.send(f"⚙️ Текущие настройки спама:\n"
                      f"• Лимит: {SPAM_LIMIT} сообщений\n"
                      f"• Окно: {SPAM_WINDOW} секунд\n"
                      f"• Варнов до бана: {SPAM_WARNS_BEFORE_BAN}")
        return
    
    changed = []
    if limit is not None and limit > 0:
        SPAM_LIMIT = limit
        changed.append(f"лимит = {limit} сообщений")
    
    if window is not None and window > 0:
        SPAM_WINDOW = window
        changed.append(f"окно = {window} секунд")
    
    if changed:
        await ctx.send(f"✅ Настройки спама обновлены: {', '.join(changed)}")
        
        embed = discord.Embed(title="⚙️ Настройки спама изменены", color=discord.Color.blue())
        embed.add_field(name="Новые настройки", value=f"Лимит: {SPAM_LIMIT} | Окно: {SPAM_WINDOW}с", inline=False)
        embed.add_field(name="Кто изменил", value=ctx.author.mention)
        await send_log(ctx.guild, embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def lockdown(ctx):
    db["raid_mode"] = True
    save_data(db)
    await ctx.send("🔒 **РЕЖИМ ЗАЩИТЫ АКТИВИРОВАН**")
    
    embed = discord.Embed(title="🔒 РЕЖИМ ЗАЩИТЫ ВКЛЮЧЕН", color=discord.Color.red())
    embed.add_field(name="Кто включил", value=ctx.author.mention)
    await send_log(ctx.guild, embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def unlock(ctx):
    db["raid_mode"] = False
    save_data(db)
    await ctx.send("🔓 Режим защиты отключен")
    
    embed = discord.Embed(title="🔓 РЕЖИМ ЗАЩИТЫ ВЫКЛЮЧЕН", color=discord.Color.green())
    embed.add_field(name="Кто выключил", value=ctx.author.mention)
    await send_log(ctx.guild, embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def addword(ctx, *, word):
    if "banwords" not in db:
        db["banwords"] = []
    if word.lower() not in db["banwords"]:
        db["banwords"].append(word.lower())
        save_data(db)
        await ctx.send(f"✅ Слово `{word}` добавлено")
        
        embed = discord.Embed(title="📝 Добавлен банворд", color=discord.Color.blue())
        embed.add_field(name="Слово", value=word)
        embed.add_field(name="Кто добавил", value=ctx.author.mention)
        await send_log(ctx.guild, embed)
    else:
        await ctx.send(f"❌ Слово `{word}` уже в списке")

@bot.command()
@commands.has_permissions(administrator=True)
async def delword(ctx, *, word):
    if word.lower() in db.get("banwords", []):
        db["banwords"].remove(word.lower())
        save_data(db)
        await ctx.send(f"✅ Слово `{word}` удалено")
        
        embed = discord.Embed(title="📝 Удален банворд", color=discord.Color.blue())
        embed.add_field(name="Слово", value=word)
        embed.add_field(name="Кто удалил", value=ctx.author.mention)
        await send_log(ctx.guild, embed)
    else:
        await ctx.send(f"❌ Слово `{word}` не найдено")

@bot.command()
async def banwords(ctx):
    words = db.get("banwords", [])
    if words:
        await ctx.send(f"📜 Банворды: {', '.join(words)}")
    else:
        await ctx.send("📜 Список банвордов пуст")

@bot.command()
@commands.has_permissions(administrator=True)
async def trust(ctx, user: discord.User):
    if "trusted" not in db:
        db["trusted"] = []
    if user.id not in db["trusted"]:
        db["trusted"].append(user.id)
        save_data(db)
        await ctx.send(f"✅ {user.mention} добавлен в доверенные")
        
        embed = discord.Embed(title="⭐ Добавлен в доверенные", color=discord.Color.green())
        embed.add_field(name="Пользователь", value=user.mention)
        embed.add_field(name="Кто добавил", value=ctx.author.mention)
        await send_log(ctx.guild, embed)
    else:
        await ctx.send(f"❌ {user.mention} уже в доверенных")

@bot.command()
@commands.has_permissions(administrator=True)
async def untrust(ctx, user: discord.User):
    if user.id == OWNER_ID:
        await ctx.send("❌ Нельзя удалить владельца!")
        return
    if user.id in db.get("trusted", []):
        db["trusted"].remove(user.id)
        save_data(db)
        await ctx.send(f"✅ {user.mention} удален из доверенных")
        
        embed = discord.Embed(title="❌ Удален из доверенных", color=discord.Color.red())
        embed.add_field(name="Пользователь", value=user.mention)
        embed.add_field(name="Кто удалил", value=ctx.author.mention)
        await send_log(ctx.guild, embed)
    else:
        await ctx.send(f"❌ {user.mention} не в доверенных")

@bot.command()
async def config(ctx):
    embed = discord.Embed(title="⚙️ Настройки бота", color=discord.Color.blue())
    embed.add_field(name="Общих варнов до бана", value=WARNS_BEFORE_BAN, inline=True)
    embed.add_field(name="Спам-варнов до бана", value=SPAM_WARNS_BEFORE_BAN, inline=True)
    embed.add_field(name="Сброс варнов через", value=f"{WARN_EXPIRE_HOURS} часов", inline=True)
    embed.add_field(name="Спам-лимит", value=f"{SPAM_LIMIT} сообщений за {SPAM_WINDOW} сек", inline=True)
    embed.add_field(name="Доверенных", value=len(db.get("trusted", [])), inline=True)
    embed.add_field(name="Банвордов", value=len(db.get("banwords", [])), inline=True)
    embed.add_field(name="📋 Канал логов", value=f"#{LOG_CHANNEL_NAME}", inline=True)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def test_log(ctx):
    """Тестовая команда для проверки логов"""
    embed = discord.Embed(
        title="✅ ТЕСТОВЫЙ ЛОГ",
        description="Если вы видите это сообщение, канал логов работает правильно!",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    await send_log(ctx.guild, embed)
    await ctx.send("📋 Тестовый лог отправлен в канал #logs!")

# ===== ЗАПУСК =====
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ ОШИБКА: Неверный токен!")
    except Exception as e:
        print(f"❌ ОШИБКА: {e}")