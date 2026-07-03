"""
Модуль мини-игр для Telegram бота
"""
import json
import os
import random
import time
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

GAMES_FILE = "games_data.json"
FREE_KEY_COOLDOWN = 3600  # 1 час

# Айтемы для бесплатного кейса
ITEMS_FREE = [
    {"name": "🗑 Мусор", "value": 0, "weight": 30},
    {"name": "🥤 Редбулл", "value": 5, "weight": 20},
    {"name": "🧦 Носки", "value": 8, "weight": 12},
    {"name": "🍕 Пицца", "value": 10, "weight": 15},
    {"name": "📀 Пиратский диск", "value": 12, "weight": 10},
    {"name": "🎮 Скин для оружия", "value": 20, "weight": 8},
    {"name": "💎 Стразы", "value": 40, "weight": 5},
]

# Айтемы для платного кейса ($100)
ITEMS_PAID = [
    {"name": "🎧 Наушники (премиум)", "value": 30, "weight": 25},
    {"name": "⌚ Электронные часы", "value": 50, "weight": 22},
    {"name": "💍 Золотое кольцо", "value": 75, "weight": 20},
    {"name": "🎮 Приставка PS5", "value": 120, "weight": 15},
    {"name": "📱 IPhone 17", "value": 150, "weight": 10},
    {"name": "🏎 Спортивная машина", "value": 250, "weight": 5},
    {"name": "💎 Бриллиант 3 карата", "value": 400, "weight": 2},
    {"name": "🏠 Квартира в центре", "value": 800, "weight": 1},
]

def load_games() -> dict:
    try:
        with open(GAMES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_games(data: dict):
    with open(GAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_data(user_id: str) -> dict:
    data = load_games()
    if user_id not in data:
        data[user_id] = {
            "balance": 0,
            "inventory": [],
            "last_free_key_time": 0,
            "total_cases": 0,
        }
        save_games(data)
    return data[user_id]

def _save_user_data(user_id: str, user_data: dict):
    data = load_games()
    data[user_id] = user_data
    save_games(data)

def weighted_random(items: list) -> dict:
    total = sum(item["weight"] for item in items)
    r = random.randint(1, total)
    for item in items:
        r -= item["weight"]
        if r <= 0:
            return item
    return items[-1]

def get_free_key_status(user_id: str) -> dict:
    """Проверяет, доступен ли бесплатный ключ. Возвращает статус и время ожидания."""
    user = get_user_data(user_id)
    now = time.time()
    elapsed = now - user["last_free_key_time"]
    if elapsed >= FREE_KEY_COOLDOWN:
        return {"available": True, "seconds_left": 0}
    return {"available": False, "seconds_left": int(FREE_KEY_COOLDOWN - elapsed)}

def claim_free_key(user_id: str) -> bool:
    """Забирает бесплатный ключ. Возвращает True если получилось."""
    user = get_user_data(user_id)
    now = time.time()
    if now - user["last_free_key_time"] >= FREE_KEY_COOLDOWN:
        user["last_free_key_time"] = now
        _save_user_data(user_id, user)
        return True
    return False

def open_case(case_type: str, user_id: str) -> dict:
    """
    Открывает кейс. case_type: 'free' или 'paid'.
    Возвращает {'success': bool, 'item': str, 'value': int, 'message': str}
    """
    user = get_user_data(user_id)
    
    if case_type == "free":
        if not claim_free_key(user_id):
            return {"success": False, "item": "", "value": 0, "message": "❌ Ключ ещё не доступен!"}
        item = weighted_random(ITEMS_FREE)
    elif case_type == "paid":
        if user["balance"] < 100:
            return {"success": False, "item": "", "value": 0, "message": f"❌ Недостаточно денег! Нужно $100, у вас ${user['balance']}."}
        user["balance"] -= 100
        _save_user_data(user_id, user)
        item = weighted_random(ITEMS_PAID)
    else:
        return {"success": False, "item": "", "value": 0, "message": "❌ Неизвестный тип кейса."}
    
    # Добавляем в инвентарь
    user = get_user_data(user_id)  # reload
    user["inventory"].append(item["name"])
    user["total_cases"] += 1
    _save_user_data(user_id, user)
    
    return {
        "success": True,
        "item": item["name"],
        "value": item["value"],
        "message": f"🎉 Вам выпало: {item['name']}!",
    }

def sell_all_items(user_id: str) -> int:
    """Продаёт всё из инвентаря. Возвращает выручку."""
    user = get_user_data(user_id)
    if not user["inventory"]:
        return 0
    
    # Считаем стоимость
    all_items = ITEMS_FREE + ITEMS_PAID
    value_map = {item["name"]: item["value"] for item in all_items}
    
    total = 0
    for item_name in user["inventory"]:
        total += value_map.get(item_name, 0)
    
    user["balance"] += total
    user["inventory"] = []
    _save_user_data(user_id, user)
    return total

def get_inventory_text(user_id: str) -> str:
    """Возвращает текст инвентаря."""
    user = get_user_data(user_id)
    if not user["inventory"]:
        return "🎒 Инвентарь пуст."
    
    # Группируем
    from collections import Counter
    counts = Counter(user["inventory"])
    
    all_items = ITEMS_FREE + ITEMS_PAID
    value_map = {item["name"]: item["value"] for item in all_items}
    
    lines = ["🎒 Инвентарь:\n"]
    for item_name, count in sorted(counts.items()):
        value = value_map.get(item_name, 0)
        val_str = f"${value}" if value > 0 else "бесценно"
        lines.append(f"• {item_name} x{count} — {val_str}")
    
    lines.append(f"\n💰 Баланс: ${user['balance']}")
    return "\n".join(lines)

def format_time(seconds: int) -> str:
    """Форматирует секунды в читаемый вид."""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}ч {m}мин"
    return f"{m}мин {s}сек"

# ===================== Handlers =====================

async def games_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню игр."""
    keyboard = [
        [InlineKeyboardButton("🎲 Кейсы", callback_data="games:cases")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text("🎮 Игры\n\nВыбери игру:", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text("🎮 Игры\n\nВыбери игру:", reply_markup=reply_markup)

async def games_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех колбэков игр."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = str(update.effective_user.id)
    
    if data == "games:cases":
        await show_cases_menu(query, user_id)
    elif data == "games:free":
        await open_free_case_handler(query, user_id)
    elif data == "games:paid":
        await open_paid_case_handler(query, user_id)
    elif data == "games:inventory":
        await show_inventory(query, user_id)
    elif data == "games:sellall":
        await sell_all_handler(query, user_id)
    elif data == "games:main":
        await games_menu(update, context)
    elif data == "games:back_cases":
        await show_cases_menu(query, user_id)

async def show_cases_menu(query, user_id: str):
    """Показывает меню кейсов."""
    user = get_user_data(user_id)
    key_status = get_free_key_status(user_id)
    
    if key_status["available"]:
        key_text = "✅ Есть ключ!"
    else:
        remaining = format_time(key_status["seconds_left"])
        key_text = f"⏳ Ключ через: {remaining}"
    
    text = (
        f"🎲 Открытие кейсов\n\n"
        f"💰 Баланс: ${user['balance']}\n"
        f"🔑 {key_text}\n"
        f"📦 Открыто кейсов: {user['total_cases']}\n\n"
        f"Выбери кейс:"
    )
    
    keyboard = [
        [InlineKeyboardButton("📦 Бесплатный кейс", callback_data="games:free")],
        [InlineKeyboardButton("💎 Платный кейс ($100)", callback_data="games:paid")],
        [InlineKeyboardButton("🎒 Инвентарь", callback_data="games:inventory")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games:main")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def open_free_case_handler(query, user_id: str):
    """Открывает бесплатный кейс."""
    # Анимация открытия
    await query.edit_message_text("🔓 Открываем бесплатный кейс...")
    await asyncio.sleep(1)
    
    result = open_case("free", user_id)
    
    if not result["success"]:
        await show_cases_menu(query, user_id)
        return
    
    text = (
        f"{result['message']}\n"
        f"💰 Можно продать за ${result['value']}\n\n"
        f"🥳 Повезло!"
    )
    keyboard = [
        [InlineKeyboardButton("📦 Ещё бесплатный", callback_data="games:free")],
        [InlineKeyboardButton("💎 Платный кейс ($100)", callback_data="games:paid")],
        [InlineKeyboardButton("🎒 Инвентарь", callback_data="games:inventory")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games:cases")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def open_paid_case_handler(query, user_id: str):
    """Открывает платный кейс."""
    user = get_user_data(user_id)
    if user["balance"] < 100:
        await query.edit_message_text(
            f"❌ Недостаточно денег! Нужно $100, у вас ${user['balance']}.\n"
            f"Открой бесплатный кейс и продай что выпало!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 Бесплатный кейс", callback_data="games:free")],
                [InlineKeyboardButton("🔙 Назад", callback_data="games:cases")],
            ])
        )
        return
    
    # Анимация
    await query.edit_message_text("💎 Открываем платный кейс...")
    await asyncio.sleep(1.5)
    
    result = open_case("paid", user_id)
    
    if not result["success"]:
        await show_cases_menu(query, user_id)
        return
    
    text = (
        f"{result['message']}\n"
        f"💰 Можно продать за ${result['value']}\n\n"
        f"🔥 Красавчик!"
    )
    keyboard = [
        [InlineKeyboardButton("💎 Ещё платный ($100)", callback_data="games:paid")],
        [InlineKeyboardButton("📦 Бесплатный кейс", callback_data="games:free")],
        [InlineKeyboardButton("🎒 Инвентарь", callback_data="games:inventory")],
        [InlineKeyboardButton("🔙 Назад", callback_data="games:cases")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_inventory(query, user_id: str):
    """Показывает инвентарь."""
    user = get_user_data(user_id)
    text = get_inventory_text(user_id)
    
    keyboard = []
    if user["inventory"]:
        keyboard.append([InlineKeyboardButton("💰 Продать всё", callback_data="games:sellall")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="games:cases")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def sell_all_handler(query, user_id: str):
    """Продаёт всё из инвентаря."""
    total = sell_all_items(user_id)
    if total == 0:
        await query.edit_message_text(
            "❌ Инвентарь пуст, нечего продавать.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="games:cases")],
            ])
        )
        return
    
    await query.edit_message_text(
        f"💰 Продано всё! Выручка: ${total}\n"
        f"Теперь у вас ${get_user_data(user_id)['balance']}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Платный кейс ($100)", callback_data="games:paid")],
            [InlineKeyboardButton("📦 Бесплатный кейс", callback_data="games:free")],
            [InlineKeyboardButton("🎒 Инвентарь", callback_data="games:inventory")],
            [InlineKeyboardButton("🔙 Назад", callback_data="games:cases")],
        ])
    )
