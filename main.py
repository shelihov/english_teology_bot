
import logging
import random
import asyncio
import sqlite3
import json
from dotenv import load_dotenv
import os

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.filters import CommandStart, Command


# Загрузка токена из .env
load_dotenv()
API_TOKEN = os.getenv('API_TOKEN')

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())

import glob
# Загрузка всех словарей
def load_dictionaries():
    dicts = {}
    for file in glob.glob("*.json"):
        # Можно добавить фильтр, чтобы не брать служебные файлы, если потребуется
        name = file.split(".")[0]
        with open(file, "r", encoding="utf-8") as f:
            dicts[name] = json.load(f)
    return dicts

DICTIONARIES = load_dictionaries()
DEFAULT_DICT = list(DICTIONARIES.keys())[0] if DICTIONARIES else None

DB_FILE = "users.db"
conn = sqlite3.connect(DB_FILE)
c = conn.cursor()
# Новая схема: составной ключ (user_id, dict)
create_table_sql = '''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER,
    dict TEXT,
    seen TEXT,
    unseen TEXT,
    current INTEGER,
    PRIMARY KEY (user_id, dict)
)'''
c.execute(create_table_sql)
conn.commit()

# Утилиты работы с БД
def get_user(user_id):
    # Получаем текущий словарь для пользователя
    c.execute("SELECT dict FROM users WHERE user_id = ? ORDER BY rowid DESC LIMIT 1", (user_id,))
    dict_row = c.fetchone()
    if not DICTIONARIES or DEFAULT_DICT is None:
        return [], [], -1, None
    dict_name = dict_row[0] if dict_row else DEFAULT_DICT
    # Получаем прогресс по выбранному словарю
    c.execute("SELECT seen, unseen, current FROM users WHERE user_id = ? AND dict = ?", (user_id, dict_name))
    row = c.fetchone()
    if row:
        seen = json.loads(row[0])
        unseen = json.loads(row[1])
        current = row[2]
    else:
        dict_len = len(DICTIONARIES[dict_name])
        seen = []
        unseen = list(range(dict_len))
        current = -1
        c.execute("INSERT INTO users (user_id, dict, seen, unseen, current) VALUES (?, ?, ?, ?, ?)", (user_id, dict_name, json.dumps(seen), json.dumps(unseen), current))
        conn.commit()
    return seen, unseen, current, dict_name

def update_user(user_id, seen, unseen, current, dict_name=None):
    if dict_name is not None:
        c.execute("UPDATE users SET seen = ?, unseen = ?, current = ? WHERE user_id = ? AND dict = ?", (json.dumps(seen), json.dumps(unseen), current, user_id, dict_name))
    else:
        # dict_name обязателен для уникальности
        pass
    conn.commit()

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_menu_keyboard(selected_dict=None):
    dict_buttons = [[KeyboardButton(text=f"Словарь: {name}")] for name in DICTIONARIES.keys()]
    menu = dict_buttons
    menu.append([KeyboardButton(text="Выдать текст")])
    menu.append([KeyboardButton(text="📊 Статистика")])
    return ReplyKeyboardMarkup(keyboard=menu, resize_keyboard=True)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    _, _, _, dict_name = get_user(message.from_user.id)
    if dict_name is None:
        await message.answer("❌ Нет доступных словарей для работы. Пожалуйста, добавьте хотя бы один .json-файл со структурами переводов в папку.")
        return
    await message.answer(
        f"👋 Привет! Я помогу тебе практиковать философский перевод. Используй меню ниже.\nТекущий словарь: <b>{dict_name}</b>",
        reply_markup=get_menu_keyboard(dict_name)
    )

@dp.message()
async def menu_and_translation_handler(message: types.Message):
    text = message.text.strip()
    user_id = message.from_user.id
    seen, unseen, current_idx, dict_name = get_user(user_id)
    if dict_name is None:
        await message.answer("❌ Нет доступных словарей для работы. Пожалуйста, добавьте хотя бы один .json-файл со структурами переводов в папку.")
        return
    # Выбор словаря
    if text.startswith("Словарь: "):
        new_dict = text.replace("Словарь: ", "")
        if new_dict in DICTIONARIES:
            c.execute("SELECT seen, unseen, current FROM users WHERE user_id = ? AND dict = ?", (user_id, new_dict))
            row = c.fetchone()
            if row:
                seen = json.loads(row[0])
                unseen = json.loads(row[1])
                current_idx = row[2]
            else:
                dict_len = len(DICTIONARIES[new_dict])
                seen = []
                unseen = list(range(dict_len))
                current_idx = -1
                c.execute("INSERT INTO users (user_id, dict, seen, unseen, current) VALUES (?, ?, ?, ?, ?)", (user_id, new_dict, json.dumps(seen), json.dumps(unseen), current_idx))
                conn.commit()
            update_user(user_id, seen, unseen, current_idx, new_dict)
            await message.answer(f"✅ Словарь <b>{new_dict}</b> выбран!", reply_markup=get_menu_keyboard(new_dict))
        else:
            await message.answer("❌ Такой словарь не найден.", reply_markup=get_menu_keyboard(dict_name))
        return
    # Кнопка "Выдать текст"
    if text == "Выдать текст":
        if not unseen:
            await message.answer("🎉 Вы перевели все доступные тексты!", reply_markup=get_menu_keyboard(dict_name))
            return
        if dict_name not in DICTIONARIES:
            await message.answer("❌ Ошибка: выбранный словарь не найден.")
            return
        idx = random.choice(unseen)
        en_text = DICTIONARIES[dict_name][idx]["en"]
        update_user(user_id, seen, unseen, idx, dict_name)
        await message.answer(f"<b>Переведите следующий текст:</b>\n\n{en_text}\n\n<i>Отправьте свой перевод в чат</i>", reply_markup=get_menu_keyboard(dict_name))
        return
    # Кнопка "Статистика"
    if text == "📊 Статистика":
        # Собираем статистику по всем словарям
        stats = []
        for dict_key in DICTIONARIES.keys():
            c.execute("SELECT seen, unseen FROM users WHERE user_id = ? AND dict = ?", (user_id, dict_key))
            row = c.fetchone()
            if row:
                seen = json.loads(row[0])
                unseen = json.loads(row[1])
            else:
                seen = []
                unseen = list(range(len(DICTIONARIES[dict_key])))
            total = len(DICTIONARIES[dict_key])
            stats.append(f"<b>{dict_key}</b>:\nПройдено: <b>{len(seen)}</b>\nОсталось: <b>{len(unseen)}</b>\nВсего: <b>{total}</b>")
        msg = "📊 <b>Ваша статистика по всем словарям:</b>\n\n" + "\n\n".join(stats)
        await message.answer(msg, reply_markup=get_menu_keyboard(dict_name))
        return
    # Если это не кнопка меню — считаем переводом
    if current_idx == -1:
        return
    if dict_name not in DICTIONARIES:
        await message.answer("❌ Ошибка: выбранный словарь не найден.")
        return
    ru_text = DICTIONARIES[dict_name][current_idx]["ru"]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="mark_correct")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="mark_incorrect")]
    ])
    await message.answer(f"<b>Оригинальный перевод:</b>\n\n{ru_text}")
    await message.answer("Вы смогли перевести текст?", reply_markup=keyboard)

# Кнопка "Старт" в меню
## Удаляем обработку инлайн-кнопок меню и команд /menu, /stats, оставляем только ReplyKeyboard

## Удаляем обработку инлайн-кнопки "Выдать текст" — теперь только через ReplyKeyboard

## Удаляем отдельный обработчик handle_translation — теперь всё в одном

@dp.callback_query(F.data.in_(["mark_correct", "mark_incorrect"]))
async def handle_result(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    seen, unseen, current_idx, dict_name = get_user(user_id)
    if dict_name is None or dict_name not in DICTIONARIES:
        await callback.message.answer("❌ Ошибка: выбранный словарь не найден.")
        await callback.answer()
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    if callback.data == "mark_correct" and current_idx != -1:
        if current_idx not in seen:
            seen.append(current_idx)
        if current_idx in unseen:
            unseen.remove(current_idx)
        update_user(user_id, seen, unseen, -1, dict_name)
        await callback.answer("Текст отмечен как выученный.")
    elif callback.data == "mark_incorrect":
        update_user(user_id, seen, unseen, -1, dict_name)
        await callback.answer("Текст будет показан снова позже.")
    # Инлайн-клавиатура для следующего текста
    next_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Отправить следующий текст", callback_data="next_text")]
    ])
    await callback.message.answer("Хотите получить следующий текст?", reply_markup=next_keyboard)

# Обработка инлайн-кнопки 'Отправить следующий текст'
@dp.callback_query(F.data == "next_text")
async def next_text_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    seen, unseen, _, dict_name = get_user(user_id)
    if dict_name is None or dict_name not in DICTIONARIES:
        await callback.message.answer("❌ Ошибка: выбранный словарь не найден.")
        await callback.answer()
        return
    if not unseen:
        await callback.message.answer("🎉 Вы перевели все доступные тексты!", reply_markup=get_menu_keyboard(dict_name))
        await callback.answer()
        return
    idx = random.choice(unseen)
    en_text = DICTIONARIES[dict_name][idx]["en"]
    update_user(user_id, seen, unseen, idx, dict_name)
    await callback.message.answer(f"<b>Переведите следующий текст:</b>\n\n{en_text}\n\n<i>Отправьте свой перевод в чат</i>", reply_markup=get_menu_keyboard(dict_name))
    await callback.answer()

# Запуск
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
