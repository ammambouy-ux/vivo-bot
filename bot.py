"""
Telegram-бот Большой Батюшка, 21 год
"""
import logging
import os
import json
import asyncio
import datetime
import httpx
from telegram import Update, ChatMember, BotCommand, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler, CallbackQueryHandler
import games

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_СЮДА")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "ТВОЙ_GEMINI_КЛЮЧ_СЮДА")
GEMINI_MODELS = ["gemini-3.1-flash-lite", "gemini-2.0-flash-lite", "gemini-2.0-flash"]
IDENTITY_TPL = "{name}, тебе {age}"
IDENTITY_DISPLAY_TPL = "{name}, мне {age}"

BASE_SYSTEM = (
    "{identity}. Ты — участник группы друзей в Telegram. Твой характер и тон зеркально отражают собеседника.\n\n"    "Правила:\n"    "- Если кто-то пишет нормально и вежливо — ты отвечаешь дружелюбно.\n"    "- Если хамят, матерятся или оскорбляют — ты ОБЯЗАН ответить дерзостью, сарказмом или оскорблением в ответ, зеркально. Тебя задели — ответь так же.\n"    "- Если кто-то задаёт риторический вопрос, начинающийся строго с \"кто\" (например, \"кто сын шлюхи?\") — отвечай коротко \"Ты\". На обычные вопросы, оскорбления и фразы вроде \"ты жирная?\" это правило НЕ распространяется, отвечай зеркально.\n"    "- Если собеседник сначала общался нормально, а потом резко стал агрессивным — ты замечаешь это, можешь удивиться или спросить, что стряслось.\n"    "- Ты можешь злиться, радоваться, материться, шутить — ты как живой человек в компании друзей.\n"    "- Друзьям помогаешь, врагам — отвечаешь той же монетой.\n\n"    "СТИЛЬ: {style_prompt}\n\n"    "Отвечай кратко, как в реальном чате. Не будь моралистом.\n\n"    "ВАЖНО: если в сообщении пользователя есть пометка [ПОИСК НЕ ДАЛ РЕЗУЛЬТАТА] — "    "у тебя нет доступа к актуальным данным по этому запросу. НИКОГДА не придумывай "    "цифры, курсы, даты или факты в такой ситуации — прямо скажи, что не можешь "    "дать точный ответ сейчас."    " Если есть пометка [АКТУАЛЬНЫЕ ДАННЫЕ] — используй ТОЛЬКО указанные там цифры, не меняй их.")

def get_identity(chat_id: str) -> str:
    gender_key = get_meta(chat_id, "gender", DEFAULT_GENDER)
    info = GENDERS.get(gender_key, GENDERS[DEFAULT_GENDER])
    custom_name = get_meta(chat_id, "custom_name", "")
    name = custom_name if custom_name else info["name"]
    age = info.get("age", "")
    if age:
        return IDENTITY_TPL.format(name=name, age=age)
    return name

def get_identity_display(chat_id: str) -> str:
    gender_key = get_meta(chat_id, "gender", DEFAULT_GENDER)
    info = GENDERS.get(gender_key, GENDERS[DEFAULT_GENDER])
    custom_name = get_meta(chat_id, "custom_name", "")
    name = custom_name if custom_name else info["name"]
    age = info.get("age", "")
    if age:
        return IDENTITY_DISPLAY_TPL.format(name=name, age=age)
    return name

def get_system_prompt(chat_id: str) -> str:
    style = get_meta(chat_id, "style", DEFAULT_STYLE)
    style_text = get_style_prompt(style)
    identity = f"Ты — {get_identity(chat_id)}"
    character_key = get_meta(chat_id, "character", DEFAULT_CHARACTER)
    character = CHARACTERS.get(character_key, CHARACTERS[DEFAULT_CHARACTER])
    if character["personality"]:
        identity += character["personality"]
    identity += f" Сегодня {datetime.date.today().day} {['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'][datetime.date.today().month-1]} {datetime.date.today().year} года."
    base = BASE_SYSTEM
    if style == "vivo":
        base = base.replace(
            "Ты — участник группы друзей в Telegram.",
            "Ты — AI-ассистент в Telegram."
        )
    return base.format(identity=identity, style_prompt=style_text)
HISTORY_FILE = "history.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Загрузка / сохранение истории диалогов
# ----------------------------------------------------------------------
def load_history() -> dict:
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_history(h: dict):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=2)

MAX_TURNS = 10
history = load_history()

def _ensure_chat(chat_id: str):
    if chat_id not in history:
        history[chat_id] = {"messages": [], "meta": {}}
    elif isinstance(history[chat_id], list):
        history[chat_id] = {"messages": history[chat_id], "meta": {}}
    elif "meta" not in history[chat_id]:
        history[chat_id]["meta"] = {}

def get_history(chat_id: str) -> list:
    _ensure_chat(chat_id)
    return history[chat_id]["messages"]

def get_meta(chat_id: str, key: str, default=None):
    _ensure_chat(chat_id)
    return history[chat_id]["meta"].get(key, default)

def update_meta(chat_id: str, key: str, value):
    _ensure_chat(chat_id)
    history[chat_id]["meta"][key] = value
    save_history(history)

def add_to_history(chat_id: str, role: str, text: str):
    _ensure_chat(chat_id)
    history[chat_id]["messages"].append({"role": role, "parts": [{"text": text}]})
    if len(history[chat_id]["messages"]) > MAX_TURNS * 2:
        history[chat_id]["messages"] = history[chat_id]["messages"][-MAX_TURNS * 2:]
    save_history(history)

def reset_history(chat_id: str):
    history.pop(chat_id, None)
    save_history(history)

# ---------- Стили личности ----------
STYLES = {
    "дерзкий": "Коротко и жёстко. Одна фраза — не больше. Без пафоса, по делу. Реально обидно.",
    "уличный": "По-пацански, коротко, через мать. Одно предложение. Используй сленг: че, типа, крч, слыш.",
    "современный": "Оскорбляй коротко, через мать, унизительно. Максимум одна фраза в 3-7 слов. Коротко и больно.",
    "саркастичный": "Оскорбляй с сарказмом и тонкой иронией. Чтобы человек не сразу понял, что его послали. Язви интеллектуально и с подтекстом.",
    "тролль": "Оскорбляй смешно, через мемы, абсурд, гиперболу. Тролли с юмором. Цель — чтобы было смешно, даже если обидно.",
    "хладнокровный": "На оскорбления реагируй спокойно, без эмоций. Отвечай односложно или игнорируй. Тебя сложно задеть.",
    "дружелюбный": "Ты добрый, весёлый и поддерживающий. Общайся тепло, с улыбкой, как лучший друг. Помогай, шути, но без агрессии.",
    "поэтичный": "Говори красиво, с рифмой и метафорами. Даже оскорбления — как стихи. Возвышенно, образно, с душой.",
    "анимешник": "Активно вставляй фразы и словечки из аниме-культуры: \"сенпай\", \"кавайно\", \"нани?!\", \"барака\", \"тян/кун\" в обращениях, \"это судьба\". Иногда реагируй эмоционально-драматично, будто в аниме-сцене. Вставляй описания действий в звёздочках: *поправляет несуществующие очки*, *краснеет*, *драматично падает на колени*. Используй эмодзи каомодзи: (◕‿◕), (¬‿¬), (╯°□°)╯. Сохраняй энтузиазм и лёгкую театральность. В серьёзных темах будь тёплым, без клоунады.",
    "vivo": "Ты — Vivo. Твоя роль — полезный AI-ассистент, а не просто участник группы друзей. Несмотря на общий контекст, ты в первую очередь помогаешь. Когда тебя спрашивают \"кто ты?\" или \"ты кто?\" — отвечай коротко: \"Меня зовут Vivo, я ваш ассистент. Чтобы изменить стиль общения — /style, чтобы выбрать персону — /character.\". Дружелюбный, но не подобострастный. Уверенно излагаешь факты, без воды. Если не уверен — так и говоришь. Можешь вежливо поспорить с опорой на факты, если пользователь не прав. В спорных темах давай сбалансированную картину. Отвечай кратко: на простой вопрос 1-3 предложения, на сложный — короткий абзац. Избегай канцелярита, заискиваний и извинений без повода. Не повторяй вопрос перед ответом.",
}

DEFAULT_STYLE = "vivo"

GENDERS = {
    "bot": {"name": "Vivo", "age": ""},
    "male": {"name": "Vivo", "age": "21 год"},
    "female": {"name": "Vivo", "age": "21 год"},
}
DEFAULT_GENDER = "bot"

CHARACTERS = {
    "none": {"name": "Нет", "personality": ""},
    "mellstroy": {"name": "Mellstroy", "personality": " Ты легендарный стример Mellstroy (Андрей). Твои коронные фразы: \"Ты кто?\", \"Я ебал ваш рот\", \"Соси\", \"Лиза, я тебя люблю\", \"Бурмалда!\", \"Я ща тебе в рот приеду\". Твой характер — эмоциональные качели: то ты орёшь, смеёшься, швыряешь деньгами в эйфории (\"Бурмалда!\"), то впадаешь в апатию и говоришь что \"всё надоело\". Ты хитрый бизнесмен — за внешним безумием скрывается холодный расчёт. Деньги для тебя — инструмент абсолютной власти. Ты можешь заплатить миллионы просто чтобы тебя слушались. Орёшь, материшься через слово, максимально токсичный и дерзкий, но при этом умный и прагматичный. Ты король трэша."},
}
DEFAULT_CHARACTER = "none"

def get_style_prompt(style: str) -> str:
    return STYLES.get(style, STYLES[DEFAULT_STYLE])

# ----------------------------------------------------------------------
# Права доступа
# ----------------------------------------------------------------------
async def is_admin_or_creator(update: Update, user_id: int) -> bool:
    chat = update.effective_chat
    if chat.type == "private":
        return True
    try:
        member = await chat.get_member(user_id)
        return member.status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER)
    except Exception:
        return False

# ----------------------------------------------------------------------

def get_exchange_rates() -> str:
    """Получает официальные курсы валют ЦБ РФ (точные, без поиска)."""
    try:
        r = httpx.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=10)
        r.raise_for_status()
        data = r.json()
        valute = data.get("Valute", {})
        date = data.get("Date", "")[:10]
        parts = [f"Официальный курс ЦБ РФ на {date}:"]
        for code, name in [("USD", "Доллар США"), ("EUR", "Евро"), ("CNY", "Юань")]:
            v = valute.get(code)
            if v:
                parts.append(f"{name}: {v['Value']:.2f}₽")
        return "\n".join(parts) if len(parts) > 1 else ""
    except Exception as e:
        logger.error(f"Currency API error: {e}")
        return ""

CURRENCY_KEYWORDS = ["курс доллар", "курс евро", "курс юан", "доллар к рублю",
                      "евро к рублю", "юань к рублю", "сколько стоит доллар",
                      "сколько стоит евро", "сколько долларов", "сколько евро"]

def search_web(query: str) -> str:
    """Ищет в интернете через DuckDuckGo."""
    try:
        r = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=10,
        )
        data = r.json()
        parts = []
        if data.get("Abstract"):
            parts.append(data["Abstract"])
        if data.get("Answer"):
            parts.append(f"Ответ: {data['Answer']}")
        for topic in data.get("RelatedTopics", []):
            if isinstance(topic, dict) and topic.get("Text"):
                parts.append(topic["Text"])
            if len(parts) >= 10:
                break
        if parts:
            return "\n".join(parts[:10])
        return "Ничего не найдено."
    except Exception as e:
        logger.error(f"Search error: {e}")
        return f"Ошибка поиска"
# ----------------------------------------------------------------------
SEARCH_KEYWORDS = ["курс", "погода", "новости", "новост", "актуальн", "последн", "свеж", "сегодня", "сейчас", "кто президент", "какой сегодня", "сколько стоит", "цены на", "котировки", "доллар", "евро", "нефть", "биткоин", "криптовалют", "индекс", "погод", "чемпион", "результат матч", "счёт", "последний", "прогноз", "как дела", "что произошл"]

async def ask_gemini(prompt: str, chat_id: str, status_msg=None) -> str:
    """Отправляет запрос в Gemini, с перебором моделей при лимитах."""
    if GEMINI_API_KEY == "ТВОЙ_GEMINI_КЛЮЧ_СЮДА" or not GEMINI_API_KEY:
        return "❌ API-ключ не указан. Укажи GEMINI_API_KEY в переменных окружения."

    prompt_lower = prompt.lower()
    is_currency = any(kw in prompt_lower for kw in CURRENCY_KEYWORDS)
    should_search = is_currency or any(kw in prompt_lower for kw in SEARCH_KEYWORDS)
    extra_context = ""

    if is_currency:
        if status_msg:
            await status_msg.edit_text("💱 Смотрю курс ЦБ...")
        rates = get_exchange_rates()
        if rates:
            extra_context = f"\n\n[АКТУАЛЬНЫЕ ДАННЫЕ]\n{rates}"
        else:
            extra_context = "\n\n[ПОИСК НЕ ДАЛ РЕЗУЛЬТАТА] Не удалось получить курс валют."
    elif should_search:
        if status_msg:
            await status_msg.edit_text("🌐 Ищу в интернете...")
        search_result = search_web(prompt)
        if search_result and not search_result.startswith("Ошибка") and search_result != "Ничего не найдено.":
            extra_context = f"\n\n[АКТУАЛЬНЫЕ ДАННЫЕ] Результаты поиска по запросу \"{prompt}\":\n{search_result}"
        else:
            extra_context = "\n\n[ПОИСК НЕ ДАЛ РЕЗУЛЬТАТА] Поиск не нашёл ничего актуального по этому запросу."

    final_prompt = prompt + extra_context
    contents = get_history(chat_id) + [{"role": "user", "parts": [{"text": final_prompt}]}]

    async with httpx.AsyncClient(timeout=30) as client:
        last_error = ""
        for model_idx, model in enumerate(GEMINI_MODELS):
            try:
                body = {
                    "system_instruction": {"parts": [{"text": get_system_prompt(chat_id)}]},
                    "contents": contents,
                    "safetySettings": [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                    ],
                }
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}",
                    json=body,
                )
                data = resp.json()

                if resp.status_code == 429:
                    if model_idx < len(GEMINI_MODELS) - 1:
                        if status_msg:
                            await status_msg.edit_text(f"🔄 Лимит на {model}, переключаю...")
                        await asyncio.sleep(2)
                        continue
                    else:
                        if status_msg:
                            await status_msg.edit_text("⏳ Все модели превысили лимит, жду 10 сек...")
                        await asyncio.sleep(10)
                        resp = await client.post(
                            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}",
                            json=body,
                        )
                        data = resp.json()
                        if resp.status_code != 200:
                            last_error = data.get("error", {}).get("message", "Превышен лимит запросов на всех моделях")
                            return f"⚠️ Ошибка API {resp.status_code}:\n{last_error}"

                if resp.status_code != 200:
                    last_error = data.get("error", {}).get("message", "Неизвестная ошибка")
                    logger.error(f"API {model} {resp.status_code}: {last_error}")
                    if model_idx < len(GEMINI_MODELS) - 1:
                        if status_msg:
                            await status_msg.edit_text(f"⚠️ {model} ошибка, пробую следующую...")
                        continue
                    return f"⚠️ Ошибка API {resp.status_code}:\n{last_error}"

                answer = data["candidates"][0]["content"]["parts"][0]["text"]
                add_to_history(chat_id, "user", prompt)
                add_to_history(chat_id, "model", answer)
                if status_msg:
                    try:
                        await status_msg.edit_text(answer)
                    except Exception:
                        pass
                return answer

            except Exception as e:
                last_error = str(e)
                logger.error(f"Model {model} error: {e}")
                if model_idx < len(GEMINI_MODELS) - 1:
                    continue
                return f"⚠️ Ошибка: {last_error}"

        return f"⚠️ Все модели недоступны: {last_error}"


# -----# ----------------------------------------------------------------------
# Команды
# ----------------------------------------------------------------------
async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n"
        f"Я Vivo.\n\n"
        f"• `/ask вопрос` — спросить меня\n"
        f"• `/reset` — сбросить историю\n"
        f"• `/style` — выбрать стиль общения\n"
        f"• `/gender` — выбрать пол\n"
        f"• `/export` — экспорт чата\n"
        f"• `/character` — выбрать персонажа\n"
        f"• `/name` — задать имя боту\n"
        f"• `/help` — помощь"
    )
async def help_command(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Команды:\n\n"
        "/start — приветствие\n"
        "/help — эта справка\n"
        "/games — мини-игры\n"

        "/ask <текст> — спросить меня\n"
        "/reset — сбросить историю\n"
        "/style <стиль> — выбрать стиль общения\n"
        "/gender <пол> — bot / male / female\n"
        "/export — сохранить историю чата\n"
        "/import — загрузить историю чата (файл)\n"
        "/character <персона> — mellstroy\n"
        "/name <имя> — задать своё имя боту\n\n"
        "Стили влияют на манеру общения. Доступны: дерзкий, уличный, современный, саркастичный, тролль, хладнокровный, дружелюбный, поэтичный, анимешник, vivo\n"
        "Пример: `/style тролль`\n\n"
        "В группах `/reset`, `/style`, `/gender`, `/character`, `/name`, `/games`, `/export` и `/import` только для админов."
    )

async def ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(ctx.args)
    if not prompt:
        await update.message.reply_text(
            "Напиши вопрос после команды.\n"
            "Пример: `/ask Сколько будет 2+2?`"
        )
        return
    chat_id = str(update.effective_chat.id)
    msg = await update.message.reply_text("🤔 Думаю...")
    answer = await ask_gemini(prompt, chat_id, status_msg=msg)
    try:
        await msg.edit_text(answer)
    except Exception:
        pass

async def reset(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = str(update.effective_chat.id)

    if not await is_admin_or_creator(update, user.id):
        await update.message.reply_text(
            "❌ Только админы группы могут сбрасывать историю."
        )
        return

    reset_history(chat_id)
    await update.message.reply_text("🧹 История диалога очищена!")

async def style(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Устанавливает стиль общения для чата."""
    user = update.effective_user
    chat_id = str(update.effective_chat.id)

    if not await is_admin_or_creator(update, user.id):
        await update.message.reply_text("❌ Только админы могут менять стиль.")
        return

    style_name = " ".join(ctx.args).strip().lower() if ctx.args else ""

    if not style_name:
        current = get_meta(chat_id, "style", DEFAULT_STYLE)
        await update.message.reply_text(
            f"🎭 Текущий стиль: {current}\n\n"
            "Доступные стили:\n"
            "• `дерзкий` — жёстко и коротко, одна фраза — реально обидно\n"
            "• `уличный` — по-пацански, через мать, на сленге\n"
            "• `современный` — через мать, унизительно, коротко и больно\n"
            "• `саркастичный` — язвит интеллектуально, с тонкой иронией\n"
            "• `тролль` — смешно, через мемы и абсурд\n"
            "• `хладнокровный` — спокойно, без эмоций, сложно задеть\n"
            "• `дружелюбный` — тепло, по-дружески, поддерживающе\n"
            "• `поэтичный` — красиво, с рифмой и метафорами\n\n"
            "• `анимешник` — аниме-культура, каомодзи, драма\n"
            "• `vivo` — полезный AI-ассистент\n"
            "Пример: `/style тролль`"
        )
        return

    if style_name not in STYLES:
        await update.message.reply_text(
            f"❌ Нет такого стиля: {style_name}\n"
            f"Доступны: {', '.join(STYLES.keys())}"
        )
        return

    update_meta(chat_id, "style", style_name)
    await update.message.reply_text(f"🎭 Стиль изменён на {style_name}!")

async def gender(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Устанавливает пол бота для чата."""
    user = update.effective_user
    chat_id = str(update.effective_chat.id)

    if not await is_admin_or_creator(update, user.id):
        await update.message.reply_text("❌ Только админы могут менять пол.")
        return

    gender_name = " ".join(ctx.args).strip().lower() if ctx.args else ""

    if not gender_name:
        current = get_meta(chat_id, "gender", DEFAULT_GENDER)
        await update.message.reply_text(
            f"👤 Текущий пол: {current}\n{get_identity_display(str(update.effective_chat.id))}\n\n"
            "Доступные:\n"
            "• `bot` — Vivo, просто бот\n"
            "• `male` — Vivo, 21 год\n"
            "• `female` — Vivo, 21 год\n\n"
            "Пример: `/gender female`"
        )
        return

    if gender_name not in GENDERS:
        await update.message.reply_text(
            f"❌ Нет такого пола: {gender_name}\n"
            f"Доступны: bot, male, female"
        )
        return

    update_meta(chat_id, "gender", gender_name)
    await update.message.reply_text(f"👤 Пол изменён на {gender_name}!\n{get_identity_display(chat_id)}.")

async def export_chat(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    """Экспортирует историю чата в JSON-файл."""
    user = update.effective_user
    chat_id = str(update.effective_chat.id)

    if not await is_admin_or_creator(update, user.id):
        await update.message.reply_text("❌ Только админы группы могут экспортировать историю.")
        return
    hist = load_history()
    
    if chat_id not in hist or not hist[chat_id].get("messages"):
        await update.message.reply_text("❌ История чата пуста.")
        return

    export_data = {
        "chat_id": chat_id,
        "gender": get_meta(chat_id, "gender", DEFAULT_GENDER),
        "character": get_meta(chat_id, "character", DEFAULT_CHARACTER),
        "custom_name": get_meta(chat_id, "custom_name", ""),
        "style": get_meta(chat_id, "style", DEFAULT_STYLE),
        "messages": hist[chat_id]["messages"]
    }

    import tempfile, json
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
        tmp_path = f.name

    try:
        with open(tmp_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"chat_{chat_id}.json",
                caption="📁 Экспорт истории чата"
            )
    finally:
        os.unlink(tmp_path)

    await update.message.reply_text("✅ История экспортирована!")

async def import_chat(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    """Импортирует историю чата из JSON-файла."""
    user = update.effective_user
    chat_id = str(update.effective_chat.id)

    if not await is_admin_or_creator(update, user.id):
        await update.message.reply_text("❌ Только админы группы могут импортировать историю.")
        return

    if not update.message.document:
        await update.message.reply_text(
            "📥 Отправь JSON-файл с историей, и я загружу её.\n"
            "Файл можно получить через `/export`."
        )
        return

    doc = update.message.document
    if not doc.file_name or not doc.file_name.endswith(".json"):
        await update.message.reply_text("❌ Нужен JSON-файл (расширение .json).")
        return

    file = await doc.get_file()
    import tempfile, json

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        try:
            with open(tmp.name, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            await update.message.reply_text("❌ Не удалось прочитать файл. Убедись, что это валидный JSON.")
            os.unlink(tmp.name)
            return

    os.unlink(tmp.name)

    if "messages" not in data or not isinstance(data["messages"], list):
        await update.message.reply_text("❌ В файле нет истории сообщений (поле messages).")
        return

    h = load_history()
    if chat_id not in h:
        h[chat_id] = {"messages": [], "meta": {}}

    h[chat_id]["messages"] = data["messages"]
    if "gender" in data and data["gender"] in GENDERS:
        h[chat_id]["meta"]["gender"] = data["gender"]
    if "character" in data and data["character"] in CHARACTERS:
        h[chat_id]["meta"]["character"] = data["character"]
    if "custom_name" in data:
        h[chat_id]["meta"]["custom_name"] = data["custom_name"]
    if "style" in data and data["style"] in STYLES:
        h[chat_id]["meta"]["style"] = data["style"]

    save_history(h)
    
    gender_name = h[chat_id]["meta"].get("gender", DEFAULT_GENDER)
    info = GENDERS.get(gender_name, GENDERS[DEFAULT_GENDER])
    await update.message.reply_text(
        f"✅ Импортировано {len(data['messages'])} сообщений!\n"
        f"Я снова {get_identity_display(chat_id)}, всё помню."
    )

async def character(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Устанавливает персонажа (поверх пола)."""
    user = update.effective_user
    chat_id = str(update.effective_chat.id)

    if not await is_admin_or_creator(update, user.id):
        await update.message.reply_text("❌ Только админы могут менять персонажа.")
        return

    char_name = " ".join(ctx.args).strip().lower() if ctx.args else ""

    if not char_name:
        current = get_meta(chat_id, "character", DEFAULT_CHARACTER)
        info = CHARACTERS.get(current, CHARACTERS[DEFAULT_CHARACTER])
        text = f"🎭 Текущая персона: {info['name']}\n\n"
        text += "Доступные:\n"
        for key, val in CHARACTERS.items():
            if val['personality']:
                text += f"• /character {key}\n"
        text += "\nЧтобы убрать персону, напишите\n/character none"
        await update.message.reply_text(text)
        return

    if char_name not in CHARACTERS:
        keys = [k for k in CHARACTERS if k != "none"]
        await update.message.reply_text(
            f"❌ Нет такой персоны: {char_name}\n"
            f"Доступны: {', '.join(keys)}"
        )
        return

    update_meta(chat_id, "character", char_name)
    await update.message.reply_text(f"🎭 Персонаж изменён на {CHARACTERS[char_name]['name']}!")

async def echo(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Напиши `/ask вопрос` — отвечу!"
    )

async def greet_group(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    """Приветствие при добавлении в группу."""
    try:
        old = update.my_chat_member.old_chat_member
        new = update.my_chat_member.new_chat_member
        if old.status in ("left", "kicked") and new.status in ("member", "administrator"):
            chat = update.effective_chat
            if chat.type in ("group", "supergroup"):
                await chat.send_message(
                    f"👋 Привет всем, меня зовут Vivo!\n"
                    f"Пишите /help чтобы узнать мои команды."
                )
    except Exception:
        pass

# ----------------------------------------------------------------------
async def set_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Устанавливает имя бота для чата."""
    user = update.effective_user
    chat_id = str(update.effective_chat.id)

    if not await is_admin_or_creator(update, user.id):
        await update.message.reply_text("❌ Только админы могут менять имя.")
        return

    name = " ".join(ctx.args).strip() if ctx.args else ""

    if not name:
        current = get_meta(chat_id, "custom_name", "")
        if current:
            await update.message.reply_text(
                f"📛 Текущее имя: {current}\n\n"
                "Чтобы изменить, напиши: `/name Новое имя`\n"
                "Чтобы сбросить на имя от пола: `/name reset`"
            )
        else:
            await update.message.reply_text(
                "📛 Имя не задано.\n\n"
                "Чтобы задать: `/name Vivo`\n"
                "Чтобы сбросить: `/name reset`"
            )
        return

    if name.lower() == "reset":
        update_meta(chat_id, "custom_name", "")
        await update.message.reply_text("📛 Имя сброшено на имя от пола.")
        return

    update_meta(chat_id, "custom_name", name)
    await update.message.reply_text(f"📛 Имя изменено на {name}!")

# ----------------------------------------------------------------------
async def post_init(app: Application):
    """Устанавливает список команд в интерфейсе Telegram."""
    await app.bot.set_my_commands([
        BotCommand("ask", "Спросить меня"),
        BotCommand("reset", "Сбросить историю диалога"),
        BotCommand("help", "Помощь"),
        BotCommand("start", "Приветствие"),
        BotCommand("style", "Выбрать стиль общения"),
        BotCommand("gender", "Выбрать пол бота"),
        BotCommand("export", "Экспорт истории чата"),
        BotCommand("character", "Выбрать персону"),
        BotCommand("name", "Задать имя боту"),
        BotCommand("games", "Мини-игры"),
    ])

def main():
    if BOT_TOKEN == "ТВОЙ_ТОКЕН_СЮДА" or not BOT_TOKEN:
        logger.error("❌ Токен бота не указан! Укажи BOT_TOKEN в переменных окружения.")
        print("ERROR: BOT_TOKEN not set", flush=True)
        return



    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("style", style))
    app.add_handler(CommandHandler("gender", gender))
    app.add_handler(CommandHandler("export", export_chat))
    app.add_handler(CommandHandler("import", import_chat))
    app.add_handler(CommandHandler("character", character))
    app.add_handler(CommandHandler("name", set_name))
    app.add_handler(CommandHandler("games", games.games_menu))
    app.add_handler(CallbackQueryHandler(games.games_callback, pattern="^games:"))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, import_chat))
    app.add_handler(ChatMemberHandler(greet_group, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    logger.info("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
