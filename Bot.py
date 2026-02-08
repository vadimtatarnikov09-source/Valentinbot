import asyncio
import json
import os
import sqlite3
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

import requests
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, FSInputFile, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================= CONFIG =================
BOT_TOKEN = "8300929540:AAE06KzAdFi_t2TD-jTTkFGbUCywI4tB7nA"
KIE_API_KEY = "156752f1ed34819ecb236f7060494a14"
ADMIN_IDS = [5876092687]  

CREATE_URL = "https://api.kie.ai/api/v1/jobs/createTask"
INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"

# База данных
DB_FILE = "users.db"
CARDS_FOLDER = "cards"
os.makedirs(CARDS_FOLDER, exist_ok=True)

# Коллекция открыток
CARDS_TEMPLATES = {
    "birthday": {
        "name": "🎂 С Днем Рождения",
        "prompt": "birthday card with beautiful design, congratulations",
        "time_estimate": 45  # секунды
    },
    "valentine": {
        "name": "❤️ С Днем Влюбленных", 
        "prompt": "valentine's day card, romantic, hearts, love",
        "time_estimate": 50
    }
}

# Промокоды (код: сумма)
PROMO_CODES = {
    "WELCOME100": 100,
    "NEWYEAR2024": 50,
    "VALENTINE": 30,
    "BIRTHDAY": 25
}

# ================ ИНИЦИАЛИЗАЦИЯ ================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ================ БАЗА ДАННЫХ ================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        balance INTEGER DEFAULT 100,
        cards_created INTEGER DEFAULT 0,
        is_admin BOOLEAN DEFAULT 0,
        registration_date TEXT,
        last_active TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        card_type TEXT,
        image_path TEXT,
        prompt TEXT,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        type TEXT,
        description TEXT,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS used_promo_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        promo_code TEXT,
        amount INTEGER,
        used_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS support_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message_id INTEGER,
        admin_message_id INTEGER,
        message_text TEXT,
        status TEXT DEFAULT 'open',
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # Добавляем админов
    for admin_id in ADMIN_IDS:
        cursor.execute('''
        INSERT OR IGNORE INTO users 
        (user_id, username, first_name, last_name, balance, is_admin, registration_date)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        ''', (admin_id, "admin", "Admin", "Admin", 999999, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

def save_user_data(user_id: int, username: str, first_name: str, last_name: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    if not cursor.fetchone():
        cursor.execute('''
        INSERT INTO users 
        (user_id, username, first_name, last_name, registration_date, last_active)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, datetime.now().isoformat(), datetime.now().isoformat()))
    else:
        cursor.execute('''
        UPDATE users 
        SET username = ?, first_name = ?, last_name = ?, last_active = ?
        WHERE user_id = ?
        ''', (username, first_name, last_name, datetime.now().isoformat(), user_id))
    
    conn.commit()
    conn.close()

def get_user_balance(user_id: int) -> int:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else 100

def is_admin(user_id: int) -> bool:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else False

def update_balance(user_id: int, amount: int, description: str = ""):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    UPDATE users 
    SET balance = balance + ?, last_active = ?
    WHERE user_id = ?
    ''', (amount, datetime.now().isoformat(), user_id))
    
    # Записываем транзакцию
    cursor.execute('''
    INSERT INTO transactions (user_id, amount, type, description, created_at)
    VALUES (?, ?, ?, ?, ?)
    ''', (user_id, amount, "deposit" if amount > 0 else "withdraw", description, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

def add_user_card(user_id: int, card_type: str, image_path: str, prompt: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO user_cards (user_id, card_type, image_path, prompt, created_at)
    VALUES (?, ?, ?, ?, ?)
    ''', (user_id, card_type, image_path, prompt, datetime.now().isoformat()))
    
    cursor.execute('UPDATE users SET cards_created = cards_created + 1 WHERE user_id = ?', (user_id,))
    
    conn.commit()
    conn.close()

def get_user_stats(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT balance, cards_created, registration_date FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            "balance": result[0],
            "cards_created": result[1],
            "registration_date": result[2]
        }
    return None

def get_all_users():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT user_id, username, first_name, last_name, balance, cards_created, 
           registration_date, last_active 
    FROM users 
    ORDER BY registration_date DESC
    ''')
    users = cursor.fetchall()
    conn.close()
    
    return users

def save_support_message(user_id: int, message_id: int, message_text: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO support_messages (user_id, message_id, message_text, created_at)
    VALUES (?, ?, ?, ?)
    ''', (user_id, message_id, message_text, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()
    return cursor.lastrowid

def update_support_message(support_id: int, admin_message_id: int, status: str = "answered"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    UPDATE support_messages 
    SET admin_message_id = ?, status = ?
    WHERE id = ?
    ''', (admin_message_id, status, support_id))
    
    conn.commit()
    conn.close()

def get_support_messages(status: str = "open"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT sm.*, u.username, u.first_name 
    FROM support_messages sm
    JOIN users u ON sm.user_id = u.user_id
    WHERE sm.status = ?
    ORDER BY sm.created_at DESC
    ''', (status,))
    messages = cursor.fetchall()
    conn.close()
    
    return messages

def check_promo_code(promo_code: str, user_id: int):
    if promo_code not in PROMO_CODES:
        return None, "❌ Неверный промокод"
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM used_promo_codes WHERE user_id = ? AND promo_code = ?', 
                  (user_id, promo_code))
    if cursor.fetchone():
        conn.close()
        return None, "❌ Вы уже использовали этот промокод"
    
    conn.close()
    return PROMO_CODES[promo_code], "✅ Промокод активирован"

def mark_promo_used(user_id: int, promo_code: str, amount: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO used_promo_codes (user_id, promo_code, amount, used_at)
    VALUES (?, ?, ?, ?)
    ''', (user_id, promo_code, amount, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

# ================ КЛАВИАТУРЫ ================
def get_main_keyboard(user_id: int = None):
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="🎨 Создать открытку", callback_data="create_card"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
        InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help"),
    )
    
    if user_id and is_admin(user_id):
        builder.add(InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin_panel"))
    
    builder.adjust(1)
    return builder.as_markup()

def get_cards_keyboard():
    builder = InlineKeyboardBuilder()
    for key, card in CARDS_TEMPLATES.items():
        builder.add(InlineKeyboardButton(
            text=f"{card['name']} (≈{card['time_estimate']} сек)", 
            callback_data=f"card_{key}"
        ))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"))
    builder.adjust(1)
    return builder.as_markup()

def get_profile_keyboard():
    buttons = [
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="🎫 Использовать промокод", callback_data="use_promo")],
        [InlineKeyboardButton(text="📖 Мои открытки", callback_data="my_cards")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_deposit_keyboard():
    buttons = [
        [
            InlineKeyboardButton(text="50 ₽ - 100 монет", callback_data="deposit_100"),
            InlineKeyboardButton(text="100 ₽ - 250 монет", callback_data="deposit_250")
        ],
        [
            InlineKeyboardButton(text="200 ₽ - 600 монет", callback_data="deposit_600"),
            InlineKeyboardButton(text="500 ₽ - 2000 монет", callback_data="deposit_2000")
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="admin_support")],
        [InlineKeyboardButton(text="➕ Пополнить баланс", callback_data="admin_add_balance")],
        [InlineKeyboardButton(text="⬅️ На главную", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_users_list_keyboard(page: int = 0, users_per_page: int = 10):
    users = get_all_users()
    total_pages = (len(users) + users_per_page - 1) // users_per_page
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * users_per_page
    end_idx = start_idx + users_per_page
    page_users = users[start_idx:end_idx]
    
    builder = InlineKeyboardBuilder()
    
    for user in page_users:
        user_id, username, first_name, last_name, balance, cards_created, _, _ = user
        name = f"{first_name} {last_name}" if first_name and last_name else username
        builder.add(InlineKeyboardButton(
            text=f"{name} - {balance} монет ({cards_created} карт)",
            callback_data=f"admin_user_{user_id}"
        ))
    
    # Навигация
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_users_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"admin_users_{page+1}"))
        builder.row(*nav_buttons)
    
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    
    return builder.as_markup()

def get_support_messages_keyboard():
    messages = get_support_messages("open")
    builder = InlineKeyboardBuilder()
    
    for msg in messages:
        msg_id, user_id, _, _, message_text, _, created_at, username, first_name = msg
        name = f"{first_name}" if first_name else username
        preview = message_text[:30] + "..." if len(message_text) > 30 else message_text
        builder.add(InlineKeyboardButton(
            text=f"👤 {name}: {preview}",
            callback_data=f"admin_support_msg_{msg_id}"
        ))
    
    builder.row(InlineKeyboardButton(text="📨 Отвеченные", callback_data="admin_support_answered"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    
    return builder.as_markup()

# ================ СОСТОЯНИЯ FSM ================
class CardCreation(StatesGroup):
    waiting_for_template = State()
    waiting_for_photo = State()
    waiting_for_text = State()

class DepositState(StatesGroup):
    waiting_for_token = State()

class PromoState(StatesGroup):
    waiting_for_promo = State()

class AdminAddBalance(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

class SupportState(StatesGroup):
    waiting_for_message = State()

# ================ ОСНОВНЫЕ ОБРАБОТЧИКИ ================
@dp.message(CommandStart())
async def start(message: Message):
    save_user_data(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )
    
    await message.answer(
        "🎉 Добро пожаловать в бот для создания открыток!\n\n"
        "Создавайте красивые открытки с помощью ИИ.\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🎉 Добро пожаловать в бот для создания открыток!\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    stats = get_user_stats(callback.from_user.id)
    
    if stats:
        reg_date = datetime.fromisoformat(stats["registration_date"]).strftime("%d.%m.%Y")
        
        text = (
            f"👤 **Ваш профиль**\n\n"
            f"💰 **Баланс:** {stats['balance']} монет\n"
            f"🖼 **Создано открыток:** {stats['cards_created']}\n"
            f"📅 **Дата регистрации:** {reg_date}\n\n"
            f"💡 *1 открытка = 10 монет*"
        )
    else:
        text = "❌ Профиль не найден"
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_profile_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "create_card")
async def create_card_start(callback: CallbackQuery, state: FSMContext):
    balance = get_user_balance(callback.from_user.id)
    if balance < 10:
        await callback.answer("❌ Недостаточно средств! Пополните баланс.", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🎨 Выберите тип открытки:\n"
        "*Время указано ориентировочно*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_cards_keyboard()
    )
    await state.set_state(CardCreation.waiting_for_template)
    await callback.answer()

@dp.callback_query(F.data.startswith("card_"))
async def select_card_type(callback: CallbackQuery, state: FSMContext):
    card_type = callback.data.split("_")[1]
    card_info = CARDS_TEMPLATES[card_type]
    
    await state.update_data(card_type=card_type)
    
    await callback.message.edit_text(
        f"🎨 Вы выбрали: **{card_info['name']}**\n"
        f"⏱ Примерное время: ~{card_info['time_estimate']} секунд\n\n"
        "📸 Теперь отправьте фото для открытки (JPEG/PNG/WEBP до 30MB):",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(CardCreation.waiting_for_photo)
    await callback.answer()

@dp.message(CardCreation.waiting_for_photo, F.photo)
async def handle_card_photo(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    
    await state.update_data(photo_file_id=file_info.file_id)
    await message.answer("📝 Теперь отправьте текст для открытки:")
    await state.set_state(CardCreation.waiting_for_text)

@dp.message(CardCreation.waiting_for_text)
async def handle_card_text(message: Message, state: FSMContext):
    user_text = message.text
    data = await state.get_data()
    
    # Проверяем баланс
    user_id = message.from_user.id
    balance = get_user_balance(user_id)
    if balance < 10:
        await message.answer("❌ Недостаточно средств. Пополните баланс!")
        await state.clear()
        return
    
    # Списываем средства
    update_balance(user_id, -10, "Создание открытки")
    
    # Генерируем промпт
    card_type = data['card_type']
    base_prompt = CARDS_TEMPLATES[card_type]['prompt']
    final_prompt = f"{base_prompt}: {user_text}"
    
    await message.answer(
        f"🖼 **Отправляю в обработку...**\n"
        f"⏱ *Примерное время: ~{CARDS_TEMPLATES[card_type]['time_estimate']} секунд*",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Получаем фото
    file_info = await bot.get_file(data['photo_file_id'])
    file_path = file_info.file_path
    telegram_file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KIE_API_KEY}"
    }
    
    payload = {
        "model": "nano-banana-pro",
        "callBackUrl": "",
        "input": {
            "prompt": final_prompt,
            "aspect_ratio": "1:1",
            "resolution": "1K",
            "output_format": "png",
            "image_input": [telegram_file_url]
        }
    }
    
    try:
        # Создаем задачу
        create_response = requests.post(CREATE_URL, headers=headers, json=payload).json()
        
        if create_response.get("code") != 200:
            # Возвращаем деньги при ошибке
            update_balance(user_id, 10, "Возврат: ошибка создания задачи")
            await message.answer("❌ Ошибка при создании задачи. Деньги возвращены.")
            await state.clear()
            return
        
        task_id = create_response["data"]["taskId"]
        
        # Ждем результат с прогрессом
        result_url = None
        for i in range(30):
            await asyncio.sleep(2)
            
            info_response = requests.get(
                INFO_URL,
                headers={"Authorization": f"Bearer {KIE_API_KEY}"},
                params={"taskId": task_id}
            ).json()
            
            state_status = info_response["data"]["state"]
            
            if state_status == "success":
                result_json = json.loads(info_response["data"]["resultJson"])
                result_url = result_json["resultUrls"][0]
                break
            
            if state_status == "fail":
                update_balance(user_id, 10, "Возврат: ошибка генерации")
                await message.answer("❌ Ошибка генерации. Деньги возвращены.")
                await state.clear()
                return
            
            # Отправляем прогресс каждые 10 секунд
            if i % 5 == 0:
                progress = min(100, int((i / 30) * 100))
                await message.edit_text(
                    f"🔄 **Генерация...** {progress}%\n"
                    f"⏱ Осталось ~{60 - (i*2)} секунд"
                )
        
        if not result_url:
            update_balance(user_id, 10, "Возврат: время истекло")
            await message.answer("⏳ Время ожидания истекло. Деньги возвращены.")
            await state.clear()
            return
        
        # Скачиваем и сохраняем изображение
        response = requests.get(result_url)
        timestamp = int(datetime.now().timestamp())
        card_filename = f"{CARDS_FOLDER}/{user_id}_{timestamp}.png"
        
        with open(card_filename, 'wb') as f:
            f.write(response.content)
        
        # Сохраняем в БД
        add_user_card(user_id, card_type, card_filename, user_text)
        
        # Отправляем результат
        new_balance = balance - 10
        await message.answer_photo(
            photo=FSInputFile(card_filename),
            caption=(
                f"✅ **Открытка создана!**\n\n"
                f"💬 **Ваш текст:** {user_text}\n"
                f"💰 **Списано:** 10 монет\n"
                f"🎫 **Баланс:** {new_balance} монет"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_keyboard(user_id)
        )
        
    except Exception as e:
        update_balance(user_id, 10, f"Возврат: ошибка {str(e)}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}\nДеньги возвращены.")
    
    await state.clear()

@dp.callback_query(F.data == "deposit")
async def deposit_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "💰 **Пополнение баланса**\n\n"
        "Выберите способ пополнения:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_deposit_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("deposit_"))
async def select_deposit_amount(callback: CallbackQuery, state: FSMContext):
    amount_map = {
        "deposit_100": (100, 50),
        "deposit_250": (250, 100),
        "deposit_600": (600, 200),
        "deposit_2000": (2000, 500)
    }
    
    amount, price = amount_map.get(callback.data, (100, 50))
    
    # Генерируем случайный токен (имитация платежа)
    token = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
    
    await callback.message.edit_text(
        f"💳 **Оплата {price} ₽**\n\n"
        f"💰 Вы получите: **{amount} монет**\n"
        f"🔑 Ваш платежный токен: `{token}`\n\n"
        "*Для оплаты отправьте этот токен в @FasherBot*\n"
        "*После оплаты ваш баланс будет автоматически пополнен.*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Скопировать токен", callback_data=f"copy_token_{token}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="deposit")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("copy_token_"))
async def copy_token(callback: CallbackQuery):
    token = callback.data.replace("copy_token_", "")
    await callback.answer(f"Токен {token} скопирован! Отправьте его в @FasherBot", show_alert=True)

@dp.callback_query(F.data == "use_promo")
async def use_promo_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎫 **Активация промокода**\n\n"
        "Доступные промокоды:\n"
        "• WELCOME100 - 100 монет\n"
        "• NEWYEAR2024 - 50 монет\n"
        "• VALENTINE - 30 монет\n"
        "• BIRTHDAY - 25 монет\n\n"
        "Введите промокод:",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(PromoState.waiting_for_promo)
    await callback.answer()

@dp.message(PromoState.waiting_for_promo)
async def use_promo_apply(message: Message, state: FSMContext):
    promo_code = message.text.upper().strip()
    amount, msg = check_promo_code(promo_code, message.from_user.id)
    
    if amount:
        update_balance(message.from_user.id, amount, f"Промокод: {promo_code}")
        mark_promo_used(message.from_user.id, promo_code, amount)
        
        new_balance = get_user_balance(message.from_user.id)
        await message.answer(
            f"{msg}\n"
            f"💰 **Начислено:** {amount} монет\n"
            f"🎫 **Новый баланс:** {new_balance} монет",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
    else:
        await message.answer(
            f"{msg}\nПопробуйте другой промокод:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")]
            ])
        )
    
    await state.clear()

@dp.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    await callback.message.edit_text(
        "ℹ️ **Помощь по боту**\n\n"
        "🎨 **Создать открытку** - создайте уникальную открытку с помощью ИИ\n\n"
        "📋 **Процесс создания:**\n"
        "1. Выберите тип открытки\n"
        "2. Отправьте фото\n"
        "3. Добавьте текст\n"
        "4. Подождите ~45-50 секунд\n"
        "5. Получите результат!\n\n"
        "💰 **Стоимость:** 10 монет за 1 открытку\n\n"
        "👤 **В профиле вы можете:**\n"
        "• Проверить баланс\n"
        "• Пополнить баланс\n"
        "• Использовать промокод\n"
        "• Посмотреть историю открыток\n\n"
        "❓ **Проблемы?** Напишите в поддержку!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 Написать в поддержку", callback_data="support")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "support")
async def support_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📞 **Связь с поддержкой**\n\n"
        "Опишите вашу проблему или вопрос:\n"
        "*Мы ответим в течение 24 часов*",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(SupportState.waiting_for_message)
    await callback.answer()

@dp.message(SupportState.waiting_for_message)
async def support_message_received(message: Message, state: FSMContext):
    support_id = save_support_message(message.from_user.id, message.message_id, message.text)
    
    # Отправляем админам
    for admin_id in ADMIN_IDS:
        try:
            admin_msg = await bot.send_message(
                admin_id,
                f"📨 **Новое обращение в поддержку**\n\n"
                f"👤 Пользователь: {message.from_user.full_name}\n"
                f"🆔 ID: {message.from_user.id}\n"
                f"💬 Сообщение: {message.text}\n\n"
                f"📝 ID обращения: {support_id}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Ответить", callback_data=f"admin_reply_{support_id}")]
                ])
            )
            update_support_message(support_id, admin_msg.message_id, "delivered")
        except Exception as e:
            print(f"Не удалось отправить админу {admin_id}: {e}")
    
    await message.answer(
        "✅ Ваше сообщение отправлено в поддержку!\n"
        "Мы ответим вам в ближайшее время.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )
    await state.clear()

@dp.callback_query(F.data == "my_cards")
async def show_my_cards(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT card_type, prompt, created_at 
    FROM user_cards 
    WHERE user_id = ? 
    ORDER BY created_at DESC 
    LIMIT 10
    ''', (user_id,))
    
    cards = cursor.fetchall()
    conn.close()
    
    if not cards:
        await callback.message.edit_text(
            "📭 У вас еще нет созданных открыток",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎨 Создать открытку", callback_data="create_card")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")]
            ])
        )
        await callback.answer()
        return
    
    text = "📖 **Ваши последние открытки:**\n\n"
    for i, (card_type, prompt, created_at) in enumerate(cards, 1):
        card_name = CARDS_TEMPLATES.get(card_type, {}).get('name', 'Неизвестно')
        date = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
        text += f"{i}. **{card_name}**\n"
        text += f"   💬 {prompt[:30]}...\n"
        text += f"   📅 {date}\n\n"
    
    text += f"\nВсего создано: {len(cards)} открыток"
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")]
        ])
    )
    await callback.answer()

# ================ АДМИН ПАНЕЛЬ ================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🛠 **Админ-панель**\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(balance) FROM users')
    total_balance = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT SUM(cards_created) FROM users')
    total_cards = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM users WHERE last_active > ?', 
                  ((datetime.now() - timedelta(days=1)).isoformat(),))
    active_today = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM support_messages WHERE status = "open"')
    open_support = cursor.fetchone()[0]
    
    conn.close()
    
    text = (
        "📊 **Статистика бота**\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🎯 Активных за сутки: {active_today}\n"
        f"💰 Общий баланс: {total_balance} монет\n"
        f"🖼 Создано открыток: {total_cards}\n"
        f"📨 Открытых обращений: {open_support}\n\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    users = get_all_users()
    
    await callback.message.edit_text(
        f"👥 **Все пользователи**\n"
        f"Всего: {len(users)} пользователей\n\n"
        "*Нажмите на пользователя для управления:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_users_list_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_users_"))
async def admin_users_page(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    try:
        page = int(callback.data.split("_")[2])
    except:
        page = 0
    
    users = get_all_users()
    total_pages = (len(users) + 10 - 1) // 10
    
    await callback.message.edit_text(
        f"👥 **Все пользователи**\n"
        f"Всего: {len(users)} пользователей\n"
        f"Страница: {page+1}/{total_pages}\n\n"
        "*Нажмите на пользователя для управления:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_users_list_keyboard(page)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_user_"))
async def admin_user_detail(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    
    cursor.execute('SELECT COUNT(*) FROM user_cards WHERE user_id = ?', (user_id,))
    cards_count = cursor.fetchone()[0]
    
    conn.close()
    
    if user:
        _, username, first_name, last_name, balance, cards_created, is_admin, reg_date, last_active = user
        name = f"{first_name} {last_name}" if first_name and last_name else username
        
        last_active_date = datetime.fromisoformat(last_active).strftime("%d.%m.%Y %H:%M") if last_active else "никогда"
        reg_date_formatted = datetime.fromisoformat(reg_date).strftime("%d.%m.%Y")
        
        text = (
            f"👤 **Пользователь:** {name}\n"
            f"🆔 **ID:** {user_id}\n"
            f"👑 **Админ:** {'✅' if is_admin else '❌'}\n"
            f"💰 **Баланс:** {balance} монет\n"
            f"🖼 **Открыток создано:** {cards_count}\n"
            f"📅 **Регистрация:** {reg_date_formatted}\n"
            f"🕐 **Последняя активность:** {last_active_date}"
        )
    else:
        text = "❌ Пользователь не найден"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Пополнить баланс", callback_data=f"admin_add_to_{user_id}")],
        [InlineKeyboardButton(text="➖ Списать баланс", callback_data=f"admin_sub_from_{user_id}")],
        [InlineKeyboardButton(text="📧 Написать сообщение", callback_data=f"admin_msg_to_{user_id}")],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="admin_users")]
    ])
    
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "admin_support")
async def admin_support_messages(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    messages = get_support_messages("open")
    
    if not messages:
        await callback.message.edit_text(
            "📨 **Обращения в поддержку**\n\n"
            "✅ Нет новых обращений",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
            ])
        )
    else:
        await callback.message.edit_text(
            f"📨 **Обращения в поддержку**\n\n"
            f"📫 Новых обращений: {len(messages)}\n\n"
            "*Выберите обращение для ответа:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_support_messages_keyboard()
        )
    
    await callback.answer()

@dp.callback_query(F.data == "admin_support_answered")
async def admin_support_answered(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT sm.*, u.username, u.first_name 
    FROM support_messages sm
    JOIN users u ON sm.user_id = u.user_id
    WHERE sm.status = 'answered'
    ORDER BY sm.created_at DESC
    LIMIT 20
    ''')
    messages = cursor.fetchall()
    conn.close()
    
    if not messages:
        text = "📭 Нет отвеченных обращений"
    else:
        text = "📨 **Отвеченные обращения:**\n\n"
        for msg in messages:
            msg_id, user_id, _, _, message_text, _, created_at, username, first_name = msg
            name = f"{first_name}" if first_name else username
            date = datetime.fromisoformat(created_at).strftime("%d.%m.%Y")
            text += f"👤 {name} ({date}): {message_text[:30]}...\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_support")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_reply_"))
async def admin_reply_to_support(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    support_id = int(callback.data.split("_")[2])
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_id, message_text FROM support_messages WHERE id = ?', (support_id,))
    result = cursor.fetchone()
    
    if result:
        user_id, message_text = result
        await state.update_data(support_id=support_id, user_id=user_id)
        
        await callback.message.edit_text(
            f"📨 **Ответ на обращение**\n\n"
            f"💬 Оригинальное сообщение: {message_text}\n\n"
            f"✏️ Введите ваш ответ:",
            parse_mode=ParseMode.MARKDOWN
        )
        await state.set_state(SupportState.waiting_for_message)
    else:
        await callback.answer("❌ Обращение не найдено", show_alert=True)
    
    conn.close()
    await callback.answer()

@dp.message(SupportState.waiting_for_message)
async def admin_send_reply(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    if 'support_id' not in data:
        return
    
    support_id = data['support_id']
    user_id = data['user_id']
    
    try:
        # Отправляем ответ пользователю
        await bot.send_message(
            user_id,
            f"📨 **Ответ от поддержки**\n\n"
            f"{message.text}\n\n"
            f"💬 *Если у вас остались вопросы, ответьте на это сообщение*",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Обновляем статус обращения
        update_support_message(support_id, message.message_id, "answered")
        
        await message.answer(
            "✅ Ответ отправлен пользователю!",
            reply_markup=get_admin_keyboard()
        )
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение: {str(e)}")
    
    await state.clear()

@dp.callback_query(F.data == "admin_add_balance")
async def admin_add_balance_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "➕ **Пополнение баланса**\n\n"
        "Введите ID пользователя:",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(AdminAddBalance.waiting_for_user_id)
    await callback.answer()

@dp.message(AdminAddBalance.waiting_for_user_id)
async def admin_add_balance_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    try:
        user_id = int(message.text)
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            await state.update_data(user_id=user_id)
            await message.answer(
                f"👤 Пользователь найден: @{user[0]}\n\n"
                f"Введите сумму для пополнения (можно отрицательную для списания):"
            )
            await state.set_state(AdminAddBalance.waiting_for_amount)
        else:
            await message.answer("❌ Пользователь не найден. Попробуйте снова:")
    except ValueError:
        await message.answer("❌ Введите числовой ID:")

@dp.message(AdminAddBalance.waiting_for_amount)
async def admin_add_balance_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    try:
        amount = int(message.text)
        data = await state.get_data()
        user_id = data['user_id']
        
        update_balance(user_id, amount, f"Админ {message.from_user.id}")
        new_balance = get_user_balance(user_id)
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                f"💰 **Баланс обновлен администратором**\n\n"
                f"📊 Изменение: {amount:+} монет\n"
                f"🎫 Новый баланс: {new_balance} монет",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        
        await message.answer(
            f"✅ Баланс пользователя {user_id} изменен на {amount} монет\n"
            f"💰 Новый баланс: {new_balance}",
            reply_markup=get_admin_keyboard()
        )
        
    except ValueError:
        await message.answer("❌ Введите число:")
    
    await state.clear()

@dp.callback_query(F.data.startswith("admin_add_to_"))
async def admin_add_to_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[3])
    
    await callback.message.edit_text(
        f"➕ **Пополнение баланса пользователю {user_id}**\n\n"
        f"Введите сумму для пополнения:",
        parse_mode=ParseMode.MARKDOWN
    )
    await AdminAddBalance.waiting_for_amount.set()
    await callback.answer()

# ================ КОМАНДЫ ================
@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен!")
        return
    
    await message.answer(
        "🛠 **Админ-панель**\n\n"
        "Используйте кнопки ниже для управления ботом:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_admin_keyboard()
    )

# ================ ЗАПУСК ================
async def main():
    # Инициализируем БД
    init_db()
    
    print("=" * 50)
    print("🤖 Бот запущен!")
    print(f"👑 Админы: {ADMIN_IDS}")
    print("=" * 50)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())