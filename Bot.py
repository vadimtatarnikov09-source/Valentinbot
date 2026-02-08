import asyncio
import json
import os
import sqlite3
import random
import string
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional

import aiohttp
import requests
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, FSInputFile, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from yookassa import Configuration, Payment

# ================= CONFIG =================
BOT_TOKEN = "8300929540:AAE06KzAdFi_t2TD-jTTkFGbUCywI4tB7nA"
KIE_API_KEY = "156752f1ed34819ecb236f7060494a14"
ADMIN_IDS = [5876092687, 190796855]  # Добавлен второй админ

# ЮKassa конфигурация
Configuration.account_id = "1263603"
Configuration.secret_key = "test_Ki0CcEfYK0tg6KRLH65J_wQj00O2pDz1tgRUsEXnZAs"
YOOKASSA_RETURN_URL = "https://t.me/congratulator_aibot"

# База данных
DB_FILE = "users.db"
CARDS_FOLDER = "cards"
os.makedirs(CARDS_FOLDER, exist_ok=True)

# Коллекция открыток
CARDS_TEMPLATES = {
    "birthday": {
        "name": "🎂 День рождения",
        "prompt": "birthday card with beautiful design, congratulations, cake, balloons",
        "example": "Пример: Поздравляю с Днем рождения! Желаю счастья и здоровья!"
    },
    "confession": {
        "name": "💖 Признание",
        "prompt": "romantic card, love confession, hearts, flowers, emotional",
        "example": "Пример: Ты самое лучшее, что случилось со мной!"
    },
    "support": {
        "name": "🤗 Поддержка",
        "prompt": "supportive card, encouragement, empathy, comfort, warm colors",
        "example": "Пример: Я рядом! Все будет хорошо!"
    },
    "giveaway": {
        "name": "🎁 Розыгрыш",
        "prompt": "giveaway announcement, prizes, celebration, excitement",
        "example": "Пример: Розыгрыш iPhone 15! Участвуй и выигрывай!"
    },
    "celebration": {
        "name": "🎉 Праздник",
        "prompt": "celebration card, party, confetti, festive mood",
        "example": "Пример: С праздником! Ура!"
    },
    "wedding": {
        "name": "💍 Свадьба",
        "prompt": "wedding card, rings, bride and groom, elegant design",
        "example": "Пример: Поздравляю с днем свадьбы! Любви и гармонии!"
    },
    "kids": {
        "name": "🧸 Для детей",
        "prompt": "children card, cartoon characters, bright colors, fun",
        "example": "Пример: Для самого лучшего ребенка на свете!"
    },
    "no_reason": {
        "name": "🌈 Без повода",
        "prompt": "beautiful card, random act of kindness, simple design",
        "example": "Пример: Просто так, чтобы ты улыбнулся!"
    },
    "custom": {
        "name": "✏️ Свой вариант",
        "prompt": "",
        "example": "Опишите свою идею для открытки"
    }
}

# Пакеты подписок
SUBSCRIPTION_PLANS = {
    "week": {
        "name": "Еженедельная",
        "price": 299,
        "duration_days": 7,
        "generations": 7,
        "type": "week"
    },
    "month": {
        "name": "Ежемесячная",
        "price": 799,
        "duration_days": 30,
        "generations": 30,
        "type": "month"
    }
}

# Кэш для платежей
payment_cache = {}

# ================ ИНИЦИАЛИЗАЦИЯ ================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)


# ================ БАЗА ДАННЫХ ================
def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        free_generations_left INTEGER DEFAULT 3,
        paid_generations_left INTEGER DEFAULT 0,
        total_generations_used INTEGER DEFAULT 0,
        is_admin BOOLEAN DEFAULT 0,
        registration_date TEXT,
        last_active TEXT,
        referral_tag TEXT,
        telegram_balance INTEGER DEFAULT 0
    )
    ''')

    # Таблица тегов (меток) для реферальных ссылок
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tag_name TEXT UNIQUE,
        created_by INTEGER,
        created_at TEXT,
        total_users INTEGER DEFAULT 0,
        free_users INTEGER DEFAULT 0,
        paid_users INTEGER DEFAULT 0,
        active_subscriptions INTEGER DEFAULT 0,
        week_subscriptions INTEGER DEFAULT 0,
        month_subscriptions INTEGER DEFAULT 0,
        stars_payments INTEGER DEFAULT 0,
        stars_buyers INTEGER DEFAULT 0,
        stars_amount INTEGER DEFAULT 0,
        total_revenue INTEGER DEFAULT 0
    )
    ''')

    # Таблица подписок
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        status TEXT DEFAULT 'active',
        plan_type TEXT,
        payment_method_id TEXT,
        price INTEGER,
        generations INTEGER,
        current_period_start TEXT,
        expires_at TEXT,
        next_payment_date TEXT,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')

    # Таблица открыток
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

    # Таблица логов действий
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action_type TEXT,
        action_data TEXT,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')

    # Добавляем админов
    for admin_id in ADMIN_IDS:
        cursor.execute('''
        INSERT OR IGNORE INTO users 
        (user_id, username, first_name, last_name, free_generations_left, is_admin, registration_date)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        ''', (admin_id, "admin", "Admin", "Admin", 9999, datetime.now().isoformat()))

    conn.commit()
    conn.close()


def log_user_action(user_id: int, action_type: str, action_data: str = ""):
    """Логирование действий пользователя"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO user_actions (user_id, action_type, action_data, created_at)
    VALUES (?, ?, ?, ?)
    ''', (user_id, action_type, action_data, datetime.now().isoformat()))

    # Отправляем уведомление админам
    user_info = get_user_info(user_id)
    if action_type == "registration":
        for admin_id in ADMIN_IDS:
            try:
                tag_info = f"\n🏷 Метка: {user_info['referral_tag']}" if user_info.get('referral_tag') else ""
                asyncio.create_task(bot.send_message(
                    admin_id,
                    f"👤 Новый пользователь!\n"
                    f"ID: {user_id}\n"
                    f"Имя: {user_info['first_name']}\n"
                    f"Username: @{user_info.get('username', 'нет')}{tag_info}"
                ))
            except:
                pass
    elif action_type == "generation":
        for admin_id in ADMIN_IDS:
            try:
                asyncio.create_task(bot.send_message(
                    admin_id,
                    f"🎨 Пользователь сгенерировал открытку!\n"
                    f"ID: {user_id}\n"
                    f"Имя: {user_info['first_name']}\n"
                    f"Тип: {action_data}"
                ))
            except:
                pass

    conn.commit()
    conn.close()


def save_user_data(user_id: int, username: str, first_name: str, last_name: str, referral_tag: str = None):
    """Сохранение данных пользователя"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    if not cursor.fetchone():
        cursor.execute('''
        INSERT INTO users 
        (user_id, username, first_name, last_name, registration_date, last_active, referral_tag)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name,
              datetime.now().isoformat(), datetime.now().isoformat(),
              referral_tag))

        # Обновляем статистику тега
        if referral_tag:
            cursor.execute('''
            UPDATE tags SET total_users = total_users + 1 WHERE tag_name = ?
            ''', (referral_tag,))

            cursor.execute('''
            UPDATE tags SET free_users = free_users + 1 WHERE tag_name = ?
            ''', (referral_tag,))
    else:
        cursor.execute('''
        UPDATE users 
        SET username = ?, first_name = ?, last_name = ?, last_active = ?
        WHERE user_id = ?
        ''', (username, first_name, last_name, datetime.now().isoformat(), user_id))

    conn.commit()
    conn.close()

    # Логируем регистрацию
    log_user_action(user_id, "registration", referral_tag or "")


def get_user_info(user_id: int):
    """Получение информации о пользователе"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT user_id, username, first_name, last_name, free_generations_left,
           paid_generations_left, total_generations_used, registration_date,
           referral_tag, telegram_balance
    FROM users WHERE user_id = ?
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        total_generations = result[4] + result[5]
        return {
            "user_id": result[0],
            "username": result[1],
            "first_name": result[2],
            "last_name": result[3],
            "free_generations_left": result[4],
            "paid_generations_left": result[5],
            "total_generations_left": total_generations,
            "total_generations_used": result[6],
            "registration_date": result[7],
            "referral_tag": result[8],
            "telegram_balance": result[9]
        }
    return None


def get_user_subscription(user_id: int):
    """Получение информации о подписке пользователя"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT plan_type, expires_at, status, generations
    FROM subscriptions 
    WHERE user_id = ? AND status = 'active' AND expires_at > ?
    ''', (user_id, datetime.now().isoformat()))
    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            "plan_type": result[0],
            "expires_at": result[1],
            "status": result[2],
            "generations": result[3]
        }
    return None


def use_generation(user_id: int):
    """Использование одной генерации"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Сначала используем платные генерации, затем бесплатные
    cursor.execute('SELECT paid_generations_left, free_generations_left FROM users WHERE user_id = ?', (user_id,))
    paid, free = cursor.fetchone()

    if paid > 0:
        cursor.execute('''
        UPDATE users 
        SET paid_generations_left = paid_generations_left - 1,
            total_generations_used = total_generations_used + 1,
            last_active = ?
        WHERE user_id = ?
        ''', (datetime.now().isoformat(), user_id))
    elif free > 0:
        cursor.execute('''
        UPDATE users 
        SET free_generations_left = free_generations_left - 1,
            total_generations_used = total_generations_used + 1,
            last_active = ?
        WHERE user_id = ?
        ''', (datetime.now().isoformat(), user_id))
    else:
        conn.close()
        return False

    conn.commit()
    conn.close()
    return True


def add_user_card(user_id: int, card_type: str, image_path: str, prompt: str):
    """Добавление созданной открытки"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO user_cards (user_id, card_type, image_path, prompt, created_at)
    VALUES (?, ?, ?, ?, ?)
    ''', (user_id, card_type, image_path, prompt, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def save_subscription(user_id: int, plan_type: str, payment_method_id: str, price: int, generations: int):
    """Сохранение подписки пользователя"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Удаляем старые генерации и добавляем новые платные
    cursor.execute('''
    UPDATE users 
    SET paid_generations_left = ?,
        last_active = ?
    WHERE user_id = ?
    ''', (generations, datetime.now().isoformat(), user_id))

    # Сохраняем подписку
    now = datetime.now()
    expires_at = now + timedelta(days=SUBSCRIPTION_PLANS[plan_type]["duration_days"])
    next_payment = now + timedelta(days=SUBSCRIPTION_PLANS[plan_type]["duration_days"])

    cursor.execute('''
    INSERT OR REPLACE INTO subscriptions 
    (user_id, status, plan_type, payment_method_id, price, generations,
     current_period_start, expires_at, next_payment_date, created_at)
    VALUES (?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, plan_type, payment_method_id, price, generations,
          now.isoformat(), expires_at.isoformat(), next_payment.isoformat(), now.isoformat()))

    # Обновляем статистику тега
    user_info = get_user_info(user_id)
    if user_info and user_info.get('referral_tag'):
        tag = user_info['referral_tag']
        cursor.execute('SELECT paid_users FROM tags WHERE tag_name = ?', (tag,))
        current = cursor.fetchone()
        if current and current[0] == 0:
            # Первая покупка - перемещаем из бесплатных в платные
            cursor.execute('''
            UPDATE tags 
            SET paid_users = paid_users + 1,
                free_users = free_users - 1,
                total_revenue = total_revenue + ?,
                active_subscriptions = active_subscriptions + 1
            WHERE tag_name = ?
            ''', (price, tag))
        else:
            cursor.execute('''
            UPDATE tags 
            SET total_revenue = total_revenue + ?,
                active_subscriptions = active_subscriptions + 1
            WHERE tag_name = ?
            ''', (price, tag))

        # Обновляем счетчик подписок по типу
        if plan_type == "week":
            cursor.execute('UPDATE tags SET week_subscriptions = week_subscriptions + 1 WHERE tag_name = ?', (tag,))
        elif plan_type == "month":
            cursor.execute('UPDATE tags SET month_subscriptions = month_subscriptions + 1 WHERE tag_name = ?', (tag,))

    conn.commit()
    conn.close()


def update_subscription_expiry(user_id: int, plan_type: str):
    """Обновление срока действия подписки после автопродления"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    plan = SUBSCRIPTION_PLANS[plan_type]
    now = datetime.now()
    new_expires = now + timedelta(days=plan["duration_days"])
    new_next_payment = now + timedelta(days=plan["duration_days"])

    cursor.execute('''
    UPDATE subscriptions 
    SET expires_at = ?, next_payment_date = ?, current_period_start = ?
    WHERE user_id = ?
    ''', (new_expires.isoformat(), new_next_payment.isoformat(), now.isoformat(), user_id))

    # Обновляем количество генераций (заменяем старые)
    cursor.execute('''
    UPDATE users 
    SET paid_generations_left = ?
    WHERE user_id = ?
    ''', (plan["generations"], user_id))

    conn.commit()
    conn.close()


def cancel_subscription(user_id: int):
    """Отмена подписки"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    UPDATE subscriptions 
    SET status = 'cancelled'
    WHERE user_id = ?
    ''', (user_id,))

    # Обновляем статистику тега
    user_info = get_user_info(user_id)
    if user_info and user_info.get('referral_tag'):
        tag = user_info['referral_tag']
        cursor.execute('UPDATE tags SET active_subscriptions = active_subscriptions - 1 WHERE tag_name = ?', (tag,))

    conn.commit()
    conn.close()


def add_admin_tag(tag_name: str, admin_id: int):
    """Добавление тега администратором"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        cursor.execute('''
        INSERT INTO tags (tag_name, created_by, created_at)
        VALUES (?, ?, ?)
        ''', (tag_name, admin_id, datetime.now().isoformat()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_tag_stats(tag_name: str = None):
    """Получение статистики по тегам"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if tag_name:
        cursor.execute('SELECT * FROM tags WHERE tag_name = ?', (tag_name,))
        tag = cursor.fetchone()
        if tag:
            cursor.execute('''
            SELECT COUNT(DISTINCT user_id) 
            FROM users 
            WHERE referral_tag = ? AND telegram_balance > 0
            ''', (tag_name,))
            stars_buyers = cursor.fetchone()[0] or 0

            cursor.execute('''
            SELECT SUM(telegram_balance) 
            FROM users 
            WHERE referral_tag = ?
            ''', (tag_name,))
            stars_amount = cursor.fetchone()[0] or 0

            cursor.execute('''
            SELECT COUNT(*) 
            FROM users 
            WHERE referral_tag = ? AND telegram_balance > 0
            ''', (tag_name,))
            stars_payments = cursor.fetchone()[0] or 0

            return {
                "tag_name": tag[1],
                "total_users": tag[5],
                "free_users": tag[6],
                "paid_users": tag[7],
                "active_subscriptions": tag[8],
                "week_subscriptions": tag[9],
                "month_subscriptions": tag[10],
                "stars_payments": stars_payments,
                "stars_buyers": stars_buyers,
                "stars_amount": stars_amount,
                "total_revenue": tag[14]
            }
        return None
    else:
        cursor.execute('SELECT tag_name, total_users, total_revenue FROM tags')
        tags = cursor.fetchall()
        return tags


# ================ ЮKASSA ПЛАТЕЖИ ================
async def create_yookassa_payment(user_id: int, plan_type: str, is_first_payment: bool = True):
    """Создание платежа в ЮKassa для подписки"""
    try:
        plan = SUBSCRIPTION_PLANS[plan_type]

        payment_data = {
            "amount": {
                "value": str(plan["price"]),
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": YOOKASSA_RETURN_URL
            },
            "capture": True,
            "description": f"Подписка {plan['name']}",
            "metadata": {
                "user_id": user_id,
                "plan_type": plan_type,
                "generations": plan["generations"],
                "is_subscription": True,
                "is_first_payment": is_first_payment
            }
        }

        # Для первой оплаты сохраняем метод оплаты для автопродления
        if is_first_payment:
            payment_data["save_payment_method"] = True

        payment = Payment.create(payment_data, str(uuid.uuid4()))

        return payment.confirmation.confirmation_url, payment.id
    except Exception as e:
        print(f"Ошибка создания платежа: {e}")
        return None, None


async def create_recurring_payment(user_id: int, payment_method_id: str, plan_type: str):
    """Создание рекуррентного платежа для продления подписки"""
    try:
        plan = SUBSCRIPTION_PLANS[plan_type]

        payment = Payment.create({
            "amount": {
                "value": str(plan["price"]),
                "currency": "RUB"
            },
            "payment_method_id": payment_method_id,
            "capture": True,
            "description": f"Автопродление подписки {plan['name']}",
            "metadata": {
                "user_id": user_id,
                "plan_type": plan_type,
                "generations": plan["generations"],
                "is_subscription": True,
                "is_first_payment": False,
                "is_recurring": True
            }
        })

        return payment.id if payment else None
    except Exception as e:
        print(f"Ошибка создания рекуррентного платежа: {e}")
        return None


async def process_payment(payment_id: str):
    """Обработка платежа"""
    try:
        payment = Payment.find_one(payment_id)

        if payment.status == 'succeeded':
            metadata = payment.metadata
            user_id = int(metadata.get('user_id'))
            plan_type = metadata.get('plan_type')
            is_first_payment = metadata.get('is_first_payment', True)

            plan = SUBSCRIPTION_PLANS[plan_type]

            if is_first_payment:
                # Сохраняем подписку с методом оплаты
                save_subscription(
                    user_id=user_id,
                    plan_type=plan_type,
                    payment_method_id=payment.payment_method.id,
                    price=plan["price"],
                    generations=plan["generations"]
                )
            else:
                # Обновляем срок подписки для рекуррентного платежа
                update_subscription_expiry(user_id, plan_type)

            return True, plan_type
        return False, None
    except Exception as e:
        print(f"Ошибка обработки платежа: {e}")
        return False, None


# ================ КЛАВИАТУРЫ ================
def get_main_keyboard():
    """Главное меню"""
    buttons = [
        [
            InlineKeyboardButton(text="📸 Фотосессии", callback_data="photoshoot"),
            InlineKeyboardButton(text="📏 Изменить размер", callback_data="resize")
        ],
        [
            InlineKeyboardButton(text="✨ ИИ Фотошоп", callback_data="photoshop"),
            InlineKeyboardButton(text="🖼 Создать изображение", callback_data="create_image")
        ],
        [
            InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="help")
        ],
        [
            InlineKeyboardButton(text="🎭 Открытки", callback_data="cards_menu")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cards_keyboard():
    """Выбор типа открытки"""
    builder = InlineKeyboardBuilder()
    for key, card in CARDS_TEMPLATES.items():
        builder.add(InlineKeyboardButton(
            text=card['name'],
            callback_data=f"card_{key}"
        ))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"))
    builder.adjust(1)
    return builder.as_markup()


def get_balance_keyboard(has_subscription: bool = False):
    """Клавиатура баланса"""
    buttons = []

    if has_subscription:
        buttons.append([InlineKeyboardButton(text="❌ Отменить подписку", callback_data="cancel_subscription")])
    else:
        buttons.append([InlineKeyboardButton(text="💰 Оформить подписку", callback_data="subscribe")])

    buttons.append([InlineKeyboardButton(text="🎫 Промокод", callback_data="use_promo")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_subscription_keyboard():
    """Клавиатура выбора подписки"""
    builder = InlineKeyboardBuilder()

    for plan_key, plan in SUBSCRIPTION_PLANS.items():
        builder.add(InlineKeyboardButton(
            text=f"{plan['name']} - {plan['price']}₽",
            callback_data=f"subscribe_{plan_key}"
        ))

    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="balance"))
    builder.adjust(1)
    return builder.as_markup()


# ================ FSM СОСТОЯНИЯ ================
class CardCreation(StatesGroup):
    waiting_for_template = State()
    waiting_for_photo = State()
    waiting_for_text = State()
    waiting_for_custom_prompt = State()


class PromoState(StatesGroup):
    waiting_for_promo = State()


# ================ ОСНОВНЫЕ ОБРАБОТЧИКИ ================
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()

    # Парсим аргументы (реферальный тег)
    args = message.text.split()
    referral_tag = None
    if len(args) > 1:
        referral_tag = args[1]

    save_user_data(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        referral_tag=referral_tag
    )

    user_info = get_user_info(message.from_user.id)
    subscription = get_user_subscription(message.from_user.id)

    welcome_text = (
        "🎉 **Добро пожаловать в AI Фоторедактор!**\n\n"
        "✨ **Создавайте уникальные изображения с помощью ИИ**\n\n"
        f"🎯 **Доступно генераций:** {user_info['total_generations_left']}\n"
        f"📊 **Использовано:** {user_info['total_generations_used']}\n"
    )

    if subscription:
        expires_date = datetime.fromisoformat(subscription["expires_at"]).strftime("%d.%m.%Y")
        welcome_text += f"\n👑 **Активная подписка:** {SUBSCRIPTION_PLANS[subscription['plan_type']]['name']}\n"
        welcome_text += f"📅 **Действует до:** {expires_date}"

    welcome_text += "\n\n👇 **Выберите действие:**"

    await message.answer(welcome_text, reply_markup=get_main_keyboard())


@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()
    user_info = get_user_info(callback.from_user.id)

    await callback.message.edit_text(
        f"🏠 **Главное меню**\n\n"
        f"🎯 **Генераций доступно:** {user_info['total_generations_left']}\n\n"
        f"Выберите действие:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "cards_menu")
async def cards_menu(callback: CallbackQuery):
    """Меню открыток"""
    await callback.message.edit_text(
        "🎨 **Создание открыток**\n\n"
        "✨ **Стоимость:** 1 генерация\n\n"
        "👇 **Выберите тип открытки:**",
        reply_markup=get_cards_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "balance")
async def show_balance(callback: CallbackQuery):
    """Показ баланса"""
    user_info = get_user_info(callback.from_user.id)
    subscription = get_user_subscription(callback.from_user.id)

    text = (
        f"💰 **Ваш баланс**\n\n"
        f"🎯 **Доступно генераций:** {user_info['total_generations_left']}\n"
        f"  • Бесплатных: {user_info['free_generations_left']}\n"
        f"  • Платных: {user_info['paid_generations_left']}\n"
        f"📊 **Всего использовано:** {user_info['total_generations_used']}\n"
        f"💎 **Баланс Telegram Stars:** {user_info['telegram_balance']}\n"
    )

    if subscription:
        plan = SUBSCRIPTION_PLANS[subscription['plan_type']]
        expires_date = datetime.fromisoformat(subscription["expires_at"]).strftime("%d.%m.%Y")
        text += f"\n👑 **Активная подписка:** {plan['name']}\n"
        text += f"💰 **Стоимость:** {plan['price']}₽\n"
        text += f"📅 **Действует до:** {expires_date}\n"
        text += f"🔄 **Автопродление:** включено"
    else:
        text += "\n🎯 **Без активной подписки**\n💡 Оформите подписку для регулярных генераций!"

    await callback.message.edit_text(
        text,
        reply_markup=get_balance_keyboard(bool(subscription))
    )
    await callback.answer()


@dp.callback_query(F.data == "subscribe")
async def subscribe_menu(callback: CallbackQuery):
    """Меню подписок"""
    text = (
        "👑 **Оформление подписки**\n\n"
        "🎯 **Пакеты подписок:**\n\n"
        "• **Еженедельная** (7 генераций)\n"
        "  ⏰ Срок: 7 дней\n"
        "  💰 Цена: 299₽\n"
        "  🔄 Автопродление: каждую неделю\n\n"
        "• **Ежемесячная** (30 генераций)\n"
        "  ⏰ Срок: 30 дней\n"
        "  💰 Цена: 799₽\n"
        "  🔄 Автопродление: каждый месяц\n\n"
        "⚠️ **Важно:**\n"
        "• Неиспользованные генерации сгорают\n"
        "• При продлении старые генерации заменяются\n"
        "• Отменить подписку можно в любое время\n\n"
        "👇 **Выберите подписку:**"
    )

    await callback.message.edit_text(text, reply_markup=get_subscription_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("subscribe_"))
async def subscribe_plan(callback: CallbackQuery):
    """Оформление подписки"""
    plan_type = callback.data.split("_")[1]

    if plan_type not in SUBSCRIPTION_PLANS:
        await callback.answer("❌ Неверный тип подписки", show_alert=True)
        return

    plan = SUBSCRIPTION_PLANS[plan_type]

    # Создаем платеж в ЮKassa
    payment_url, payment_id = await create_yookassa_payment(callback.from_user.id, plan_type)

    if not payment_url:
        await callback.answer("❌ Ошибка создания платежа", show_alert=True)
        return

    payment_cache[payment_id] = {
        "user_id": callback.from_user.id,
        "plan_type": plan_type
    }

    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_pay_{payment_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="subscribe")]
    ])

    await callback.message.edit_text(
        f"💰 **Оформление подписки {plan['name']}**\n\n"
        f"💵 **Сумма:** {plan['price']}₽\n"
        f"🎯 **Генераций:** {plan['generations']}\n"
        f"⏰ **Срок действия:** {plan['duration_days']} дней\n"
        f"🔄 **Автопродление:** включено\n\n"
        f"💡 **Как работает автопродление:**\n"
        f"1. Сохраняем ваш способ оплаты\n"
        f"2. Автоматически списываем каждые {plan['duration_days']} дней\n"
        f"3. Вы можете отменить в любое время\n\n"
        f"👇 **Для оплаты:**",
        reply_markup=buttons
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("check_pay_"))
async def check_payment(callback: CallbackQuery):
    """Проверка платежа"""
    payment_id = callback.data.split("_")[2]

    if payment_id not in payment_cache:
        await callback.answer("❌ Платеж не найден", show_alert=True)
        return

    success, plan_type = await process_payment(payment_id)

    if success:
        plan = SUBSCRIPTION_PLANS[plan_type]
        expires_date = (datetime.now() + timedelta(days=plan["duration_days"])).strftime("%d.%m.%Y")

        await callback.message.edit_text(
            f"✅ **Подписка активирована!**\n\n"
            f"👑 **Тариф:** {plan['name']}\n"
            f"🎯 **Генераций:** {plan['generations']}\n"
            f"💰 **Стоимость:** {plan['price']}₽\n"
            f"📅 **Действует до:** {expires_date}\n"
            f"🔄 **Автопродление:** включено\n\n"
            f"✨ Теперь вы можете создавать изображения!\n"
            f"💡 Неиспользованные генерации сгорят после {expires_date}",
            reply_markup=get_main_keyboard()
        )

        # Удаляем из кэша
        del payment_cache[payment_id]

        # Логируем покупку
        log_user_action(callback.from_user.id, "subscription", plan_type)

    else:
        await callback.answer("❌ Платеж не найден или еще не обработан", show_alert=True)

    await callback.answer()


@dp.callback_query(F.data == "cancel_subscription")
async def cancel_subscription_handler(callback: CallbackQuery):
    """Отмена подписки"""
    subscription = get_user_subscription(callback.from_user.id)

    if not subscription:
        await callback.answer("❌ У вас нет активной подписки", show_alert=True)
        return

    cancel_subscription(callback.from_user.id)

    await callback.message.edit_text(
        "✅ **Подписка отменена!**\n\n"
        "🚫 **Автопродление отключено**\n"
        "💰 **Доступные генерации останутся до конца периода**\n"
        "💡 Вы можете оформить новую подписку в любое время",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


# ================ ОБРАБОТКА ОТКРЫТОК ================
@dp.callback_query(F.data.startswith("card_"))
async def select_card_type(callback: CallbackQuery, state: FSMContext):
    """Выбор типа открытки"""
    card_type = callback.data.split("_")[1]
    card_info = CARDS_TEMPLATES[card_type]

    user_info = get_user_info(callback.from_user.id)

    if user_info['total_generations_left'] < 1:
        await callback.answer(
            "❌ Недостаточно генераций!\n"
            "Пополните баланс в разделе '💰 Баланс'",
            show_alert=True
        )
        return

    await state.update_data(card_type=card_type)

    if card_type == "custom":
        await callback.message.edit_text(
            f"✏️ **Вы выбрали: Свой вариант**\n\n"
            f"📝 **Опишите, какую открытку хотите создать:**\n"
            f"Примеры:\n• Милая открытка с котиками\n• Строгое поздравление для коллеги\n• Веселая анимация\n\n"
            f"💡 *Опишите подробнее для лучшего результата*"
        )
        await state.set_state(CardCreation.waiting_for_custom_prompt)
    else:
        # Показываем пример картинки
        await callback.message.edit_text(
            f"🎨 **Вы выбрали:** {card_info['name']}\n"
            f"🎯 **Стоимость:** 1 генерация\n"
            f"📝 **Пример текста:** {card_info['example']}\n\n"
            f"📸 **Отправьте фото для открытки:**\n"
            f"(JPEG/PNG/WEBP до 30MB)"
        )
        await state.set_state(CardCreation.waiting_for_photo)

    await callback.answer()


@dp.message(CardCreation.waiting_for_custom_prompt)
async def handle_custom_prompt(message: Message, state: FSMContext):
    """Обработка кастомного промпта"""
    await state.update_data(custom_prompt=message.text)
    await message.answer(
        "✅ **Промпт сохранен!**\n\n"
        "📸 **Теперь отправьте фото для открытки:**\n"
        "(JPEG/PNG/WEBP до 30MB)"
    )
    await state.set_state(CardCreation.waiting_for_photo)


@dp.message(CardCreation.waiting_for_photo, F.photo)
async def handle_card_photo(message: Message, state: FSMContext):
    """Обработка фото для открытки"""
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)

    await state.update_data(photo_file_id=file_info.file_id)
    await message.answer(
        "📝 **Теперь отправьте текст для открытки:**\n"
        "(Что написать на открытке?)"
    )
    await state.set_state(CardCreation.waiting_for_text)


@dp.message(CardCreation.waiting_for_text)
async def handle_card_text(message: Message, state: FSMContext):
    """Финальный этап создания открытки"""
    user_text = message.text
    data = await state.get_data()

    user_id = message.from_user.id

    # Проверяем и используем генерацию
    if not use_generation(user_id):
        await message.answer(
            "❌ Недостаточно генераций!\n"
            "Пополните баланс в разделе '💰 Баланс'"
        )
        await state.clear()
        return

    card_type = data['card_type']
    if card_type == "custom":
        final_prompt = f"{data['custom_prompt']}: {user_text}"
    else:
        base_prompt = CARDS_TEMPLATES[card_type]['prompt']
        final_prompt = f"{base_prompt}: {user_text}"

    # Сообщение о генерации
    processing_msg = await message.answer(
        "🔄 **Генерация открытки...**\n"
        "⏳ Пожалуйста, подождите 30-60 секунд\n"
        "✨ Идет создание уникального дизайна..."
    )

    try:
        # Генерация через API
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

        create_response = requests.post(
            "https://api.kie.ai/api/v1/jobs/createTask",
            headers=headers,
            json=payload
        )

        if create_response.status_code != 200:
            raise Exception("Ошибка API")

        create_data = create_response.json()

        if create_data.get("code") != 200:
            raise Exception(f"API error: {create_data.get('message', 'Unknown error')}")

        task_id = create_data["data"]["taskId"]

        # Ожидание результата
        result_url = None
        for i in range(30):
            await asyncio.sleep(2)

            info_response = requests.get(
                "https://api.kie.ai/api/v1/jobs/recordInfo",
                headers={"Authorization": f"Bearer {KIE_API_KEY}"},
                params={"taskId": task_id}
            ).json()

            state_status = info_response["data"]["state"]

            if state_status == "success":
                result_json = json.loads(info_response["data"]["resultJson"])
                result_url = result_json["resultUrls"][0]
                break

            if state_status == "fail":
                raise Exception("Ошибка генерации изображения")

        if not result_url:
            raise Exception("Время ожидания истекло")

        # Сохранение открытки
        response = requests.get(result_url)
        timestamp = int(datetime.now().timestamp())
        card_filename = f"{CARDS_FOLDER}/{user_id}_{timestamp}.png"

        with open(card_filename, 'wb') as f:
            f.write(response.content)

        add_user_card(user_id, card_type, card_filename, user_text)

        await processing_msg.delete()

        user_info = get_user_info(user_id)

        # Отправляем результат
        await message.answer_photo(
            photo=FSInputFile(card_filename),
            caption=(
                f"✅ **Открытка создана!**\n\n"
                f"💬 **Текст:** {user_text}\n"
                f"🎯 **Осталось генераций:** {user_info['total_generations_left']}\n"
                f"📊 **Всего использовано:** {user_info['total_generations_used']}"
            )
        )

        # Кнопки управления
        control_buttons = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Создать еще", callback_data="cards_menu")],
            [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
        ])

        await message.answer(
            "Что вы хотите сделать дальше?",
            reply_markup=control_buttons
        )

        # Логируем генерацию
        log_user_action(user_id, "generation", card_type)

        # Удаляем временный файл
        try:
            os.remove(card_filename)
        except:
            pass

    except Exception as e:
        # Возвращаем генерацию при ошибке
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE users 
        SET free_generations_left = free_generations_left + 1,
            total_generations_used = total_generations_used - 1
        WHERE user_id = ?
        ''', (user_id,))
        conn.commit()
        conn.close()

        await message.answer(
            f"❌ **Ошибка при создании открытки:**\n"
            f"{str(e)}\n\n"
            f"🎯 **1 генерация возвращена на баланс.**",
            reply_markup=get_main_keyboard()
        )

    await state.clear()


# ================ ДРУГИЕ РАЗДЕЛЫ МЕНЮ ================
@dp.callback_query(F.data == "photoshoot")
async def photoshoot_menu(callback: CallbackQuery):
    """Меню фотосессий"""
    text = (
        "📸 **AI Фотосессии**\n\n"
        "Создавайте профессиональные фотосессии с помощью искусственного интеллекта!\n\n"
        "🎯 **Что умеет:**\n"
        "• Перенос стиля на фотографии\n"
        "• Смена фона и окружения\n"
        "• Ретушь и улучшение качества\n"
        "• Создание аватаров и стикеров\n\n"
        "⏳ *Раздел находится в активной разработке*\n"
        "🔜 *Скоро будет доступен*"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Попробовать (скоро)", callback_data="coming_soon")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "resize")
async def resize_menu(callback: CallbackQuery):
    """Меню изменения размера"""
    text = (
        "📏 **Изменить размер изображения**\n\n"
        "Быстрое и качественное изменение размеров ваших фотографий!\n\n"
        "🎯 **Возможности:**\n"
        "• Изменение размеров без потери качества\n"
        "• Обрезка и кадрирование\n"
        "• Пакетная обработка\n"
        "• Подготовка для соцсетей\n\n"
        "💡 *Используйте AI для лучшего результата!*\n"
        "⏳ *Раздел в разработке*"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Загрузить фото (скоро)", callback_data="coming_soon")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "photoshop")
async def photoshop_menu(callback: CallbackQuery):
    """Меню ИИ фотошопа"""
    text = (
        "✨ **AI Фотошоп**\n\n"
        "Мощные инструменты для редактирования фотографий на основе искусственного интеллекта!\n\n"
        "🛠 **Инструменты:**\n"
        "• Удаление объектов и людей с фото\n"
        "• Замена неба и фона\n"
        "• Ретушь кожи и улучшение лиц\n"
        "• Колоризация чёрно-белых фото\n"
        "• Восстановление старых фотографий\n\n"
        "🚀 *Новейшие AI-технологии!*\n"
        "🔜 *Скоро в боте*"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎭 Редактировать (скоро)", callback_data="coming_soon")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "create_image")
async def create_image_menu(callback: CallbackQuery):
    """Меню создания изображений с нуля"""
    text = (
        "🖼 **Создать изображение с нуля**\n\n"
        "Генерируйте уникальные изображения по текстовому описанию!\n\n"
        "🎨 **Что можно создать:**\n"
        "• Арты и иллюстрации в любом стиле\n"
        "• Фотографии несуществующих объектов\n"
        "• Логотипы и дизайнерские работы\n"
        "• Аниме и мультяшные персонажи\n"
        "• Абстрактные композиции\n\n"
        "✨ *Просто опишите, что хотите увидеть!*\n"
        "⏳ *Раздел в активной разработке*"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Создать (скоро)", callback_data="coming_soon")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "help")
async def help_menu(callback: CallbackQuery):
    """Меню помощи"""
    text = (
        "❓ **Помощь и поддержка**\n\n"
        "🎯 **Что такое генерации?**\n"
        "Генерации - это количество доступных созданий изображений.\n"
        "1 генерация = 1 созданное изображение.\n\n"
        "👑 **Как работают подписки?**\n"
        "1. Выбираете подписку (неделя/месяц)\n"
        "2. Оплачиваете первый период\n"
        "3. Получаете генерации на период\n"
        "4. Система автоматически продлевает подписку\n"
        "5. Можете отменить в любое время\n\n"
        "⚠️ **Важно!**\n"
        "• Неиспользованные генерации сгорают после окончания периода\n"
        "• При продлении старые генерации заменяются на новые\n\n"
        "🔄 **Проблемы с оплатой?**\n"
        "Обратитесь к администратору: @ваш_админ"
    )

    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
    ])

    await callback.message.edit_text(text, reply_markup=buttons)
    await callback.answer()


@dp.callback_query(F.data == "use_promo")
async def use_promo_start(callback: CallbackQuery, state: FSMContext):
    """Начало использования промокода"""
    await callback.message.answer(
        "🎫 **Введите промокод:**\n\n"
        "💡 Промокод дает бесплатные генерации\n"
        "📝 Введите код в формате: PROMO1234"
    )
    await state.set_state(PromoState.waiting_for_promo)
    await callback.answer()


@dp.message(PromoState.waiting_for_promo)
async def handle_promo_code(message: Message, state: FSMContext):
    """Обработка промокода"""
    # Здесь будет логика обработки промокодов
    # Пока просто заглушка

    await message.answer(
        "❌ **Промокод не найден или уже использован!**\n\n"
        "💡 Для получения промокода обратитесь к администратору",
        reply_markup=get_main_keyboard()
    )
    await state.clear()


# ================ АДМИН КОМАНДЫ ================
@dp.message(Command("admin"))
async def admin_command(message: Message):
    """Команда админ-панели"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен!")
        return

    text = (
        "🛠 **Админ-панель**\n\n"
        "📊 **Статистика:**\n"
        "• /adtag метка - добавить метку\n"
        "• /adstats метка - статистика по метке\n"
        "• /adstats_all - статистика по всем меткам\n\n"
        "💰 **Управление:**\n"
        "• /genpromo N - создать промокод на N генераций\n"
        "• /addgens ID N - добавить N генераций пользователю\n"
        "• /users - список пользователей\n\n"
        "📈 **Аналитика:**\n"
        "• /stats - общая статистика\n"
        "• /logs - последние действия\n"
        "• /subs - активные подписки\n"
    )

    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("adtag"))
async def add_tag_command(message: Message):
    """Добавление метки"""
    if message.from_user.id not in ADMIN_IDS:
        return

    try:
        _, tag_name = message.text.split(maxsplit=1)
        tag_name = tag_name.strip().lower()

        if add_admin_tag(tag_name, message.from_user.id):
            referral_link = f"https://t.me/your_bot?start={tag_name}"
            await message.answer(
                f"✅ **Метка добавлена!**\n\n"
                f"🏷 **Метка:** `{tag_name}`\n"
                f"🔗 **Реферальная ссылка:**\n`{referral_link}`\n\n"
                f"📊 **Для просмотра статистики:**\n`/adstats {tag_name}`"
            )
        else:
            await message.answer("❌ Метка уже существует!")

    except ValueError:
        await message.answer("❌ Использование: /adtag метка")


@dp.message(Command("adstats"))
async def stats_tag_command(message: Message):
    """Статистика по метке"""
    if message.from_user.id not in ADMIN_IDS:
        return

    try:
        _, tag_name = message.text.split(maxsplit=1)
        tag_name = tag_name.strip().lower()

        stats = get_tag_stats(tag_name)

        if not stats:
            await message.answer("❌ Метка не найдена!")
            return

        # Рассчитываем конверсии
        if stats["total_users"] > 0:
            conversion = (stats["paid_users"] / stats["total_users"]) * 100
            arpu = stats["total_revenue"] / stats["total_users"] if stats["total_users"] > 0 else 0
            arppu = stats["total_revenue"] / stats["paid_users"] if stats["paid_users"] > 0 else 0
        else:
            conversion = arpu = arppu = 0

        text = (
            f"📊 **Статистика по тегу {tag_name}**\n\n"
            f"👥 **Пользователей:** {stats['total_users']}\n"
            f"🆓 **Бесплатную генерацию использовали:** {stats['free_users']}\n"
            f"💰 **Покупателей:** {stats['paid_users']}\n"
            f"👑 **Активных подписок:** {stats['active_subscriptions']}\n"
            f"  • 299₽/неделя: {stats['week_subscriptions']}\n"
            f"  • 799₽/мес: {stats['month_subscriptions']}\n"
            f"⭐ **Оплаты Stars:** {stats['stars_payments']}\n"
            f"⭐ **Покупателей Stars:** {stats['stars_buyers']}\n"
            f"⭐ **Сумма Stars:** {stats['stars_amount']}\n"
            f"💰 **Выручка:** {stats['total_revenue']} ₽\n\n"
            f"📈 **Конверсия:** {conversion:.2f}%\n"
            f"📊 **ARPU:** {arpu:.2f} ₽\n"
            f"📊 **ARPPU:** {arppu:.2f} ₽"
        )

        await message.answer(text, parse_mode=ParseMode.MARKDOWN)

    except ValueError:
        await message.answer("❌ Использование: /adstats метка")


@dp.message(Command("adstats_all"))
async def stats_all_command(message: Message):
    """Статистика по всем меткам"""
    if message.from_user.id not in ADMIN_IDS:
        return

    tags = get_tag_stats()

    if not tags:
        await message.answer("📭 Нет созданных меток")
        return

    text = "📊 **Статистика по всем меткам:**\n\n"
    total_users = 0
    total_revenue = 0

    for tag in tags:
        tag_name, users, revenue = tag
        text += f"🏷 **{tag_name}:**\n"
        text += f"   👥 {users} пользователей\n"
        text += f"   💰 {revenue} ₽ выручки\n\n"
        total_users += users
        total_revenue += revenue

    text += f"📈 **Итого:**\n"
    text += f"   👥 Всего пользователей: {total_users}\n"
    text += f"   💰 Общая выручка: {total_revenue} ₽"

    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("stats"))
async def stats_command(message: Message):
    """Общая статистика"""
    if message.from_user.id not in ADMIN_IDS:
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM users WHERE total_generations_used > 0')
    active_users = cursor.fetchone()[0]

    cursor.execute('SELECT SUM(total_generations_used) FROM users')
    total_generations = cursor.fetchone()[0] or 0

    cursor.execute('SELECT COUNT(*) FROM subscriptions WHERE status = "active"')
    active_subscriptions = cursor.fetchone()[0] or 0

    cursor.execute('SELECT SUM(price) FROM subscriptions')
    total_revenue = cursor.fetchone()[0] or 0

    cursor.execute('SELECT COUNT(*) FROM tags')
    total_tags = cursor.fetchone()[0] or 0

    # Последние 7 дней
    cursor.execute('''
    SELECT DATE(registration_date), COUNT(*) 
    FROM users 
    WHERE registration_date > DATE('now', '-7 days')
    GROUP BY DATE(registration_date)
    ORDER BY DATE(registration_date) DESC
    ''')
    last_7_days = cursor.fetchall()

    conn.close()

    text = (
        "📊 **Общая статистика бота**\n\n"
        f"👥 **Всего пользователей:** {total_users}\n"
        f"🎯 **Активных (генерации >0):** {active_users}\n"
        f"🖼 **Всего генераций:** {total_generations}\n"
        f"👑 **Активных подписок:** {active_subscriptions}\n"
        f"💵 **Общая выручка:** {total_revenue}₽\n"
        f"🏷 **Создано меток:** {total_tags}\n\n"
        "📈 **Регистрации за 7 дней:**\n"
    )

    for date_str, count in last_7_days:
        text += f"  {date_str}: {count} чел.\n"

    text += f"\n📅 **Дата:** {datetime.now().strftime('%d.%m.%Y %H:%M')}"

    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("subs"))
async def subs_command(message: Message):
    """Список активных подписок"""
    if message.from_user.id not in ADMIN_IDS:
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT s.user_id, u.first_name, u.username, s.plan_type, s.expires_at, s.price
    FROM subscriptions s
    JOIN users u ON s.user_id = u.user_id
    WHERE s.status = 'active' AND s.expires_at > ?
    ORDER BY s.expires_at
    ''', (datetime.now().isoformat(),))

    subs = cursor.fetchall()
    conn.close()

    if not subs:
        await message.answer("📭 Нет активных подписок")
        return

    text = "👑 **Активные подписки:**\n\n"

    for user_id, first_name, username, plan_type, expires_at, price in subs[:20]:
        name = first_name or username or f"ID: {user_id}"
        expires_date = datetime.fromisoformat(expires_at).strftime("%d.%m.%Y")
        plan_name = "Недельная" if plan_type == "week" else "Месячная"

        text += f"👤 **{name}**\n"
        text += f"   🆔: {user_id}\n"
        text += f"   👑: {plan_name}\n"
        text += f"   💰: {price}₽\n"
        text += f"   📅: до {expires_date}\n\n"

    if len(subs) > 20:
        text += f"\n📊 ...и еще {len(subs) - 20} подписок"

    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("users"))
async def users_command(message: Message):
    """Список пользователей"""
    if message.from_user.id not in ADMIN_IDS:
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT user_id, username, first_name, total_generations_used, 
           registration_date, telegram_balance 
    FROM users 
    ORDER BY registration_date DESC 
    LIMIT 20
    ''')

    users = cursor.fetchall()
    conn.close()

    if not users:
        await message.answer("📭 Нет пользователей")
        return

    text = "👥 **Последние 20 пользователей:**\n\n"

    for user in users:
        user_id, username, first_name, generations, reg_date, balance = user

        name = first_name or username or f"ID: {user_id}"
        reg_date_short = datetime.fromisoformat(reg_date).strftime("%d.%m")

        text += f"👤 **{name}**\n"
        text += f"   🆔: {user_id}\n"
        text += f"   🖼: {generations}\n"
        text += f"   💎: {balance}\n"
        text += f"   📅: {reg_date_short}\n\n"

    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


# ================ ФОНОВЫЕ ЗАДАЧИ ================
async def check_subscription_renewals():
    """Проверка и автопродление подписок"""
    while True:
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Находим подписки, у которых скоро истекает срок
            three_days_later = (datetime.now() + timedelta(days=3)).isoformat()

            cursor.execute('''
            SELECT s.user_id, s.payment_method_id, s.plan_type, u.first_name
            FROM subscriptions s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.status = 'active' 
            AND s.next_payment_date <= ?
            ''', (three_days_later,))

            upcoming_renewals = cursor.fetchall()

            for user_id, payment_method_id, plan_type, first_name in upcoming_renewals:
                # Создаем рекуррентный платеж
                payment_id = await create_recurring_payment(user_id, payment_method_id, plan_type)

                if payment_id:
                    # Обновляем дату следующего платежа
                    next_payment = datetime.now() + timedelta(days=SUBSCRIPTION_PLANS[plan_type]["duration_days"])
                    cursor.execute('''
                    UPDATE subscriptions 
                    SET next_payment_date = ?
                    WHERE user_id = ?
                    ''', (next_payment.isoformat(), user_id))

                    # Уведомляем пользователя
                    try:
                        plan = SUBSCRIPTION_PLANS[plan_type]
                        await bot.send_message(
                            user_id,
                            f"💰 **Автопродление подписки**\n\n"
                            f"Система успешно списала {plan['price']}₽ за продление подписки {plan['name']}.\n"
                            f"📅 Следующее списание: {next_payment.strftime('%d.%m.%Y')}\n\n"
                            f"🎯 Получено генераций: {plan['generations']}\n"
                            f"💡 Неиспользованные генерации сгорят через {plan['duration_days']} дней"
                        )
                    except:
                        pass

                    # Логируем автопродление
                    log_user_action(user_id, "auto_renewal", plan_type)

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"Ошибка проверки подписок: {e}")

        # Проверяем каждые 6 часов
        await asyncio.sleep(6 * 3600)


async def check_expired_subscriptions():
    """Проверка и отмена просроченных подписок"""
    while True:
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Находим просроченные подписки
            cursor.execute('''
            SELECT s.user_id, s.plan_type, u.first_name
            FROM subscriptions s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.status = 'active' 
            AND s.expires_at < ?
            ''', (datetime.now().isoformat(),))

            expired_subs = cursor.fetchall()

            for user_id, plan_type, first_name in expired_subs:
                # Отменяем подписку
                cursor.execute('''
                UPDATE subscriptions 
                SET status = 'expired'
                WHERE user_id = ?
                ''', (user_id,))

                # Уведомляем пользователя
                try:
                    await bot.send_message(
                        user_id,
                        f"🚫 **Подписка истекла**\n\n"
                        f"Ваша подписка {SUBSCRIPTION_PLANS[plan_type]['name']} истекла.\n"
                        f"🔔 Неиспользованные генерации сгорели\n\n"
                        f"💡 Вы можете оформить новую подписку в разделе '💰 Баланс'"
                    )
                except:
                    pass

                # Логируем истечение
                log_user_action(user_id, "subscription_expired", plan_type)

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"Ошибка проверки просроченных подписок: {e}")

        # Проверяем каждые 12 часов
        await asyncio.sleep(12 * 3600)


# ================ ЗАПУСК ================
async def main():
    """Основная функция запуска"""
    # Инициализируем базу данных
    init_db()

    print("=" * 50)
    print("🤖 AI Фоторедактор запущен!")
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"🎯 Подписки: 7ген/299₽ (неделя), 30ген/799₽ (месяц)")
    print(f"🔄 Автопродление: включено")
    print(f"💾 База данных: {DB_FILE}")
    print("=" * 50)

    # Запускаем фоновые задачи
    asyncio.create_task(check_subscription_renewals())
    asyncio.create_task(check_expired_subscriptions())

    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
