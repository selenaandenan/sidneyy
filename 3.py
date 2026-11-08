import asyncio
import logging
import sqlite3
import json
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    ErrorEvent, Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, InputMediaPhoto, PreCheckoutQuery, LabeledPrice
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ================= НАСТРОЙКИ =================
TOKEN = "9017546774:AAHwgNtYCuU1k2-rPI-uPq5GknXZizYV_ps"  # Вставь сюда свой токен
ADMIN_IDS = [8794595573, 8624408698]
SELLER = "cluya"
PROOFS = "cluyaproofs"
VTB_CARD = "79041911584"

PHOTOS = {"main": "https://imgur.com/tz5fpTB"}

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ================= СОСТОЯНИЯ =================
class AdminState(StatesGroup):
    waiting_item_name = State()
    waiting_item_price = State()
    waiting_stock_key = State()
    waiting_stock_data = State()
    waiting_delete_key = State()

class GameState(StatesGroup):
    waiting_game_id = State()

class CodeState(StatesGroup):
    waiting_for_code_request = State()

class TopupState(StatesGroup):
    waiting_for_receipt = State()

# ================= БАЗА ДАННЫХ =================
conn = sqlite3.connect("shop.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Таблица пользователей (с балансом!)
cursor.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, 
    role TEXT DEFAULT 'user',
    balance REAL DEFAULT 0.0
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS items (key TEXT PRIMARY KEY, name TEXT, rub_price REAL, stars_price INTEGER, category TEXT)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS stock (id INTEGER PRIMARY KEY AUTOINCREMENT, item_key TEXT, code TEXT, is_sold INTEGER DEFAULT 0)""")

# Таблица заказов
cursor.execute("""CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    user_id INTEGER, 
    items_json TEXT, 
    total_price REAL, 
    method TEXT, 
    game_id TEXT,
    status TEXT DEFAULT 'pending', 
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
conn.commit()

# Заполняем товары (если пусто)
cursor.execute("SELECT COUNT(*) FROM items")
if cursor.fetchone()[0] == 0:
    default_items = [
        # Аккаунты
        ("us", "🇺🇸 США", 150, 150, "acc"),
        ("kz", "🇰🇿 Казахстан", 200, 200, "acc"),
        # Игры
        ("brawl_plus", "🎫 Brawl Pass Plus", 1300, 1300, "game"),
        ("robux", "⚡ Робуксы", 90, 90, "game"),
        # Premium
        ("tgp_3", "💎 TG Premium 3 мес", 1100, 1100, "tgp"),
        ("tgp_6", "💎 TG Premium 6 мес", 1500, 1500, "tgp"),
        ("tgp_12", "💎 TG Premium 12 мес", 2500, 2500, "tgp"),
    ]
    cursor.executemany("INSERT INTO items (key, name, rub_price, stars_price, category) VALUES (?, ?, ?, ?, ?)", default_items)
    conn.commit()

# ================= ВСПОМОГАТЕЛЬНЫЕ =================
async def send_menu(callback: CallbackQuery, text: str, reply_markup, photo_key=None):
    photo = PHOTOS.get(photo_key) if photo_key else None
    try:
        if photo:
            await callback.message.edit_media(media=InputMediaPhoto(media=photo, caption=text), reply_markup=reply_markup)
        else:
            await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await callback.message.delete()
            if photo: await callback.message.answer_photo(photo=photo, caption=text, reply_markup=reply_markup)
            else: await callback.message.answer(text, reply_markup=reply_markup)
        except: pass

def get_items_by_cat(cat):
    return cursor.execute("SELECT * FROM items WHERE category = ?", (cat,)).fetchall()

# ================= КЛАВИАТУРЫ =================
def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Каталог", callback_data="catalog")],
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="🆘 Поддержка", url=f"https://t.me/{SELLER}")]
    ])

def kb_catalog():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Аккаунты", callback_data="cat_acc")],
        [InlineKeyboardButton(text="🎮 Игры и Донат", callback_data="cat_game")],
        [InlineKeyboardButton(text="💎 Telegram Premium", callback_data="cat_tgp")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])

def kb_items(cat, back_cb):
    items = get_items_by_cat(cat)
    buttons = []
    row = []
    for item in items:
        row.append(InlineKeyboardButton(text=f"{item['name']} - {item['rub_price']}₽", callback_data=f"item_{item['key']}"))
        if len(row) == 2: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_pay(item_key, is_game):
    kb = []
    if is_game:
        kb.append([InlineKeyboardButton(text="💳 Купить (запрос ID)", callback_data=f"buygame_{item_key}")])
    else:
        kb.append([InlineKeyboardButton(text="⭐ Оплатить Звездами", callback_data=f"paystars_{item_key}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ================= СТАРТ =================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
    conn.commit()
    text = "🐾 <b>Добро пожаловать в Сидни Шоп!</b>\n\nВыберите раздел:"
    if PHOTOS["main"].startswith("http"):
        await message.answer_photo(photo=PHOTOS["main"], caption=text, reply_markup=kb_main())
    else:
        await message.answer(text, reply_markup=kb_main())

@dp.callback_query(F.data == "back")
async def cb_back(cb: CallbackQuery):
    await cb.message.edit_text("🏠 Главное меню", reply_markup=kb_main())

# ================= ЛИЧНЫЙ КАБИНЕТ И ПОПОЛНЕНИЕ =================
@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    user = cursor.execute("SELECT balance FROM users WHERE user_id = ?", (cb.from_user.id,)).fetchone()
    bal = user['balance'] if user else 0.0

    text = (
        f"👤 <b>Личный кабинет</b>\n\n"
        f"🆔 Ваш ID: <code>{cb.from_user.id}</code>\n"
        f"👤 Юзернейм: @{cb.from_user.username or '—'}\n\n"
        f"💰 <b>Баланс:</b> {bal:.2f} ₽\n"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="topup")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])
    await send_menu(cb, text, kb)
    await cb.answer()

@dp.callback_query(F.data == "topup")
async def cb_topup(cb: CallbackQuery, state: FSMContext):
    text = (
        f"💳 <b>Пополнение баланса</b>\n\n"
        f"Переведите нужную сумму на номер ВТБ:\n"
        f"<code>{VTB_CARD}</code>\n\n"
        f"⚠️ После перевода отправьте <b>фото/файл чека</b> сюда."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")]])
    await cb.message.edit_text(text, reply_markup=kb)
    await state.set_state(TopupState.waiting_for_receipt)
    await cb.answer()

@dp.message(TopupState.waiting_for_receipt, F.photo | F.document)
async def catch_topup_receipt(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(admin_id, file_id, 
                caption=f"💳 <b>Чек на пополнение!</b>\n👤 @{message.from_user.username} (ID: {message.from_user.id})", 
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Начислить 500₽", callback_data=f"topup_ok_{message.from_user.id}")
                ]]))
        except: pass
        
    await message.answer("⏳ Чек отправлен админу. Ожидайте начисления.")
    await state.clear()

@dp.callback_query(F.data.startswith("topup_ok_"))
async def cb_topup_ok(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    target_user = int(cb.data.split("_")[2])
    
    cursor.execute("UPDATE users SET balance = balance + 500 WHERE user_id = ?", (target_user,))
    conn.commit()
    
    await bot.send_message(target_user, "✅ <b>Баланс пополнен на 500 ₽!</b>")
    await cb.message.edit_caption(caption="✅ Чек одобрен, баланс начислен.")

# ================= КАТАЛОГ =================
@dp.callback_query(F.data == "catalog")
async def cb_catalog(cb: CallbackQuery):
    await send_menu(cb, "🛍 <b>Каталог товаров:</b>", kb_catalog())

@dp.callback_query(F.data == "cat_acc")
async def cb_cat_acc(cb: CallbackQuery):
    await send_menu(cb, "📱 <b>Аккаунты</b>", kb_items("acc", "catalog"))

@dp.callback_query(F.data == "cat_game")
async def cb_cat_game(cb: CallbackQuery):
    await send_menu(cb, "🎮 <b>Игры и Донат</b>", kb_items("game", "catalog"))

@dp.callback_query(F.data == "cat_tgp")
async def cb_cat_tgp(cb: CallbackQuery):
    await send_menu(cb, "💎 <b>Telegram Premium</b>", kb_items("tgp", "catalog"))

@dp.callback_query(F.data.startswith("item_"))
async def cb_item(cb: CallbackQuery):
    item_key = cb.data.replace("item_", "")
    item = cursor.execute("SELECT * FROM items WHERE key = ?", (item_key,)).fetchone()
    if not item: return
    is_game = (item['category'] == 'game')
    text = f"🛍 <b>{item['name']}</b>\n\n💰 Цена: <b>{item['rub_price']} ₽</b> (или {item['stars_price']} ⭐)"
    await send_menu(cb, text, kb_pay(item_key, is_game))

# ================= ДОНАТ (ЗАПРОС ID) =================
@dp.callback_query(F.data.startswith("buygame_"))
async def cb_buy_game(cb: CallbackQuery, state: FSMContext):
    item_key = cb.data.replace("buygame_", "")
    await state.update_data(item_key=item_key)
    await cb.message.edit_text("🎮 Введите ваш игровой ID или никнейм (например: 12345678):")
    await state.set_state(GameState.waiting_game_id)

@dp.message(GameState.waiting_game_id)
async def process_game_id(message: Message, state: FSMContext):
    data = await state.get_data()
    item = cursor.execute("SELECT * FROM items WHERE key = ?", (data['item_key'],)).fetchone()
    
    items_json = json.dumps([{"id": data['item_key'], "name": item['name'], "price": item['rub_price']}])
    cursor.execute("INSERT INTO orders (user_id, items_json, total_price, method, game_id) VALUES (?, ?, ?, 'game_id', ?)", 
                   (message.from_user.id, items_json, item['rub_price'], message.text))
    order_id = cursor.lastrowid
    conn.commit()
    
    await message.answer(f"✅ <b>Заявка №{order_id} создана!</b>\n\n"
                         f"🛍 Товар: {item['name']}\n"
                         f"🆔 Ваш ID: {message.text}\n"
                         f"💰 К оплате: <b>{item['rub_price']} ₽</b>\n\n"
                         f"Переведите на номер ВТБ:\n<code>{VTB_CARD}</code>\n\nИ отправьте чек сюда.")
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, 
                f"🎮 <b>НОВЫЙ ДОНАТ!</b>\n\n"
                f"👤 @{message.from_user.username}\n"
                f"🛍 {item['name']}\n"
                f"🆔 ID: <code>{message.text}</code>", 
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Выполнено", callback_data=f"complete_{order_id}")
                ]]))
        except: pass

@dp.callback_query(F.data.startswith("complete_"))
async def cb_complete(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    order_id = int(cb.data.split("_")[1])
    cursor.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (order_id,))
    conn.commit()
    await cb.message.edit_text("✅ Заявка выполнена.")

# ================= ОПЛАТА И ВЫДАЧА (STARS) =================
@dp.callback_query(F.data.startswith("paystars_"))
async def cb_pay_stars(cb: CallbackQuery):
    item_key = cb.data.replace("paystars_", "")
    item = cursor.execute("SELECT * FROM items WHERE key = ?", (item_key,)).fetchone()
    
    items_json = json.dumps([{"id": item_key, "name": item['name'], "price": item['rub_price']}])
    cursor.execute("INSERT INTO orders (user_id, items_json, total_price, method) VALUES (?, ?, ?, 'stars')", 
                   (cb.from_user.id, items_json, item['rub_price']))
    order_id = cursor.lastrowid
    conn.commit()

    await cb.message.answer_invoice(
        title=item['name'], description="Автовыдача", 
        payload=f"pay_order_{order_id}", 
        provider_token="", currency="XTR", 
        prices=[LabeledPrice(label=item['name'], amount=item['stars_price'])]
    )

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def success_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    if not payload.startswith("pay_order_"): return
    
    order_id = int(payload.replace("pay_order_", ""))
    order = cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order or order['status'] != 'pending': return
        
    items = json.loads(order['items_json'])
    
    # Если купили премиум, шлем уведомление админу, так как авто-выдачи нет
    for item in items:
        if "TG Premium" in item['name']:
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"💎 <b>Покупка Премиума!</b>\n👤 @{message.from_user.username}\nСрок: {item['name']}\nЗаказ: №{order_id}")
            await message.answer(f"💎 Вы купили <b>{item['name']}</b>!\nОжидайте, админ выдаст вам подписку.")
        else:
            # Для аккаунтов и остального - автовыдача
            stock_item = cursor.execute("SELECT id, code FROM stock WHERE item_key = ? AND is_sold = 0 LIMIT 1", (item['id'],)).fetchone()
            if stock_item:
                cursor.execute("UPDATE stock SET is_sold = 1 WHERE id = ?", (stock_item["id"],))
                conn.commit()
                delivery = stock_item["code"]
                await message.answer(f"📦 <b>{item['name']}</b>\n<code>{delivery}</code>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📩 Запросить код", callback_data=f"reqcode_{item['id']}")]]))
            else:
                await message.answer(f"⚠️ Товар {item['name']} закончился! Напишите @{SELLER}")

    cursor.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
    conn.commit()
    await message.answer("🏠 Спасибо за покупку!", reply_markup=kb_main())

# ================= ОБРАБОТКА КОРЗИНЫ С САЙТА =================
@dp.message(F.web_app_data)
async def web_app_handler(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") == "buy_cart":
            items = data.get("items", [])
            method = data.get("method")
            total_stars = data.get("total_stars", 0)
            
            if not items:
                await message.answer("❌ Корзина пуста.")
                return

            items_details = []
            total_rub = 0
            for key in items:
                item = cursor.execute("SELECT * FROM items WHERE key = ?", (key,)).fetchone()
                if item:
                    items_details.append({"id": key, "name": item['name'], "price": item['rub_price']})
                    total_rub += item['rub_price']
            
            items_json = json.dumps(items_details)
            
            cursor.execute("INSERT INTO orders (user_id, items_json, total_price, method) VALUES (?, ?, ?, ?)", 
                           (message.from_user.id, items_json, total_rub, method))
            order_id = cursor.lastrowid
            conn.commit()

            if method == "stars":
                await message.answer_invoice(
                    title="Оплата корзины",
                    description=f"Покупка {len(items)} товаров",
                    payload=f"pay_order_{order_id}", 
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice(label="Корзина", amount=total_stars)]
                )
            elif method == "rubles":
                await message.answer(
                    f"💳 <b>Оплата рублями</b>\n\n"
                    f"К оплате: <b>{total_rub} ₽</b>\n\n"
                    f"Номер ВТБ: <code>{VTB_CARD}</code>\n\n"
                    f"Отправьте чек сюда.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отменить", callback_data="catalog")]])
                )
    except Exception as e:
        logging.error(f"Ошибка webapp: {e}")
        await message.answer("Ошибка при обработке корзины с сайта.")

# ================= ОБРАБОТКА ЧЕКОВ (РУБЛИ) =================
@dp.message(F.photo | F.document)
async def catch_receipt(message: Message):
    order = cursor.execute("SELECT id, items_json FROM orders WHERE user_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1", (message.from_user.id,)).fetchone()
    if not order: return
    
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(admin_id, file_id, caption=f"🧾 <b>Чек!</b>\n👤 @{message.from_user.username}\nЗаказ №{order['id']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Выдать", callback_data=f"approve_{order['id']}")]]))
        except: pass
    await message.answer("⏳ Чек отправлен на проверку.")

@dp.callback_query(F.data.startswith("approve_"))
async def cb_approve(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    req_id = int(cb.data.split("_")[1])
    order = cursor.execute("SELECT user_id, items_json FROM orders WHERE id = ?", (req_id,)).fetchone()
    cursor.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (req_id,))
    conn.commit()
    
    items = json.loads(order['items_json'])
    for item in items:
        if "TG Premium" in item['name']:
            await bot.send_message(order['user_id'], f"💎 Оплата подтверждена! Ожидайте выдачи: {item['name']}")
        else:
            stock_item = cursor.execute("SELECT id, code FROM stock WHERE item_key = ? AND is_sold = 0 LIMIT 1", (item['id'],)).fetchone()
            if stock_item:
                cursor.execute("UPDATE stock SET is_sold = 1 WHERE id = ?", (stock_item["id"],))
                conn.commit()
                delivery = stock_item["code"]
                await bot.send_message(order['user_id'], f"✅ Оплата подтверждена!\n\n📦 <b>{item['name']}</b>\n<code>{delivery}</code>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📩 Запросить код", callback_data=f"reqcode_{item['id']}")]]))
            else:
                await bot.send_message(order['user_id'], f"⚠️ {item['name']} закончился на складе! Напишите @{SELLER}")
            
    await cb.message.edit_caption(caption=f"✅ Заказ №{req_id} выдан.")

# ================= ЗАПРОС КОДА =================
@dp.callback_query(F.data.startswith("reqcode_"))
async def cb_req_code(cb: CallbackQuery):
    item_key = cb.data.replace("reqcode_", "")
    item = cursor.execute("SELECT name FROM items WHERE key = ?", (item_key,)).fetchone()
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"🚨 <b>ЗАПРОС КОДА!</b>\n👤 @{cb.from_user.username}\n🛍 {item['name']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✍️ Отправить код", callback_data=f"sendcode_{cb.from_user.id}")]]))
        except: pass
    await cb.answer("✅ Запрос отправлен админу!", show_alert=True)

@dp.callback_query(F.data.startswith("sendcode_"))
async def cb_send_code(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: return
    await state.update_data(target_user=int(cb.data.split("_")[1]))
    await cb.message.edit_text("Введите код для клиента:")
    await state.set_state(CodeState.waiting_for_code_request)

@dp.message(CodeState.waiting_for_code_request)
async def send_code_to_user(message: Message, state: FSMContext):
    data = await state.get_data()
    await bot.send_message(data['target_user'], f"🔑 <b>Ваш код:</b>\n<code>{message.text}</code>")
    await message.answer("✅ Код отправлен!")
    await state.clear()

# ================= АДМИН-ПАНЕЛЬ =================
# ================= АДМИН-ПАНЕЛЬ (ПОЛНАЯ) =================
def kb_admin():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="adm_additem")],
        [InlineKeyboardButton(text="📦 Добавить на склад", callback_data="adm_addstock")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data="adm_delitem")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")]
    ])

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("👑 <b>Админ-панель</b>\nВыберите действие:", reply_markup=kb_admin())

@dp.callback_query(F.data == "admin_back")
async def cb_admin_back(cb: CallbackQuery):
    await cb.message.edit_text("👑 <b>Админ-панель</b>", reply_markup=kb_admin())
    await cb.answer()

# 1. Добавление товара
@dp.callback_query(F.data == "adm_additem")
async def adm_additem(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: return
    await cb.message.edit_text("Введите название товара (например: 🇺🇸 США):")
    await state.set_state(AdminState.waiting_item_name)

@dp.message(AdminState.waiting_item_name)
async def adm_item_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите цену в рублях (например: 150):")
    await state.set_state(AdminState.waiting_item_price)

@dp.message(AdminState.waiting_item_price)
async def adm_item_price(message: Message, state: FSMContext):
    try:
        price = float(message.text)
        data = await state.get_data()
        key = str(int(asyncio.get_event_loop().time()))
        cursor.execute("INSERT INTO items (key, name, rub_price, stars_price, category) VALUES (?, ?, ?, ?, 'acc')", (key, data['name'], price, int(price)))
        conn.commit()
        await message.answer(f"✅ Товар '{data['name']}' добавлен! (Ключ: {key})")
        await state.clear()
    except ValueError: await message.answer("Введите число!")

# 2. Добавление на склад
@dp.callback_query(F.data == "adm_addstock")
async def adm_addstock(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: return
    await cb.message.edit_text("Введите ключ товара (например: us):")
    await state.set_state(AdminState.waiting_stock_key)

@dp.message(AdminState.waiting_stock_key)
async def adm_stock_key(message: Message, state: FSMContext):
    await state.update_data(key=message.text.strip())
    await message.answer("Отправьте данные аккаунта (например: Номер: +7999..., Пароль: 12345):")
    await state.set_state(AdminState.waiting_stock_data)

@dp.message(AdminState.waiting_stock_data)
async def adm_stock_data(message: Message, state: FSMContext):
    data = await state.get_data()
    cursor.execute("INSERT INTO stock (item_key, code) VALUES (?, ?)", (data['key'], message.text))
    conn.commit()
    await message.answer(f"✅ Данные добавлены на склад для '{data['key']}'!")
    await state.clear()

# 3. Удаление товара
@dp.callback_query(F.data == "adm_delitem")
async def adm_delitem(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: return
    await cb.message.edit_text("Введите ключ товара, который хотите удалить (например: us):")
    await state.set_state(AdminState.waiting_delete_key)

@dp.message(AdminState.waiting_delete_key)
async def adm_delete_item(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    key = message.text.strip()
    cursor.execute("DELETE FROM items WHERE key = ?", (key,))
    cursor.execute("DELETE FROM stock WHERE item_key = ?", (key,))
    conn.commit()
    await message.answer(f"🗑 Товар с ключом '{key}' полностью удален из базы!")
    await state.clear()

# 4. Статистика
@dp.callback_query(F.data == "adm_stats")
async def cb_adm_stats(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    stock = cursor.execute("SELECT COUNT(*) FROM stock WHERE is_sold = 0").fetchone()[0]
    await cb.message.edit_text(
        f"📊 Пользователей: {users}\n📦 На складе: {stock}", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]])
    )
    await cb.answer()


# ================= ЗАПУСК =================
@dp.errors()
async def errors_handler(event: ErrorEvent):
    logging.error(f"Ошибка: {event.exception}")
    return True

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())