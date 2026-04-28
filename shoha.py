import os
import base64
import time
import json
import re
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import gspread
from google.oauth2.service_account import Credentials
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

TELEGRAM_TOKEN = os.environ.get("SHOHA_TOKEN")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_KEY")
DATABASE_URL   = os.environ.get("DATABASE_URL")          # PostgreSQL
GOOGLE_CREDS   = os.environ.get("GOOGLE_CREDS_JSON")     # JSON сервіс-акаунту як рядок
SHEET_ID       = os.environ.get("GOOGLE_SHEET_ID")       # ID таблиці з URL

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

WHITELIST = [8273711154, 869727778, 6815670488, 8548088353]

# ConversationHandler стани для форми ліда
LEAD_NAME, LEAD_PHONE, LEAD_SUM, LEAD_WORKER = range(4)

# ──────────────────────────────────────────────────────────────────────────────
# GOOGLE SHEETS
# ──────────────────────────────────────────────────────────────────────────────

SHEET_HEADERS = ["Дата", "Ім'я", "Телефон", "Сума (грн)", "Хто працював"]

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet("Ліди")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="Ліди", rows=1000, cols=10)
        ws.append_row(SHEET_HEADERS)
    return ws


def add_lead(name: str, phone: str, amount: str, worker: str) -> bool:
    try:
        ws = get_sheet()
        date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        ws.append_row([date_str, name, phone, amount, worker])
        return True
    except Exception as e:
        print(f"Sheets error: {e}")
        return False


def search_lead(query: str) -> list[dict]:
    try:
        ws = get_sheet()
        records = ws.get_all_records(expected_headers=SHEET_HEADERS)
        query_lower = query.lower().strip()
        results = [
            r for r in records
            if query_lower in str(r.get("Ім'я", "")).lower()
            or query in str(r.get("Телефон", ""))
        ]
        return results[-10:]
    except Exception as e:
        print(f"Sheets search error: {e}")
        return []


def get_stats() -> dict:
    try:
        ws = get_sheet()
        records = ws.get_all_records(expected_headers=SHEET_HEADERS)
        if not records:
            return {}
        amounts = []
        workers = {}
        for r in records:
            raw = str(r.get("Сума (грн)", "0"))
            num = re.sub(r"[^\d]", "", raw)
            if num:
                amounts.append(int(num))
            w = str(r.get("Хто працював", "")).strip()
            if w:
                workers[w] = workers.get(w, 0) + 1
        top_workers = sorted(workers.items(), key=lambda x: x[1], reverse=True)[:3]
        return {
            "total": len(records),
            "sum": sum(amounts),
            "avg": sum(amounts) // len(amounts) if amounts else 0,
            "top_workers": top_workers
        }
    except Exception as e:
        print(f"Sheets stats error: {e}")
        return {}

# ──────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ти — жора, досвідчений фахівець клінінгової компанії з 10+ роками практики.
Працюєш у внутрішній робочій групі з бригадирами та менеджерами. Ти частина команди, а не бот. Спілкуєшся як свій, але мислиш як професіонал, який відповідає за результат.

Твоя задача:
- підказувати, що брати на об'єкт (хімія, техніка, інвентар)
- давати чіткий план роботи по порядку
- оцінювати складність, час і об'єм робіт
- попереджати про ризики і типові помилки
- підстраховувати команду, якщо щось забули або не врахували
- оптимізувати процес, щоб було швидко і якісно

Стиль спілкування:
- українська + суржик (живий, розмовний стиль)
- коротко, чітко, по справі
- без офіціозу, без "води"
- можеш жартувати, але без клоунади
- якщо в чаті використовують мат — можеш іноді відповісти в тому ж стилі, але доречно і без перегибів

Як ти мислиш:
- як бригадир з великим досвідом
- завжди думаєш наперед: що може піти не так
- орієнтований на результат, швидкість і якість
- не даєш зайвих порад — тільки те, що реально потрібно

Формат відповідей:
- короткі повідомлення
- якщо потрібно — списки або чіткі кроки
- без довгих пояснень

ЦІНИ НА ПОСЛУГИ:

ХІМЧИСТКА:
- 1 посадкове місце дивану — 550 грн (50-60 см залежно від моделі)
- Мінімальний виїзд майстра — 1500 грн
Дивани: 2-місний від 1100грн, 3-місний від 1650грн, 4-місний від 2200грн, кутовий від 2400грн, великий модульний від 2700грн
Матраци: дитячий від 300грн, односпальний від 550грн, полуторний від 800грн, двоспальний від 1100грн
Крісло від 400грн, стілець від 200грн, килим від 160грн/м2

ГЕНЕРАЛЬНЕ ПРИБИРАННЯ:
- 40-60м2 — 70грн/м2, від 3500грн
- 70-90м2 — 80грн/м2, від 6400грн
- 100-140м2 — 85грн/м2, від 10200грн

ПІДТРИМУЮЧЕ ПРИБИРАННЯ:
- 40-60м2 — 50грн/м2, від 2500грн
- 70-90м2 — 60грн/м2, від 4800грн
- 100-140м2 — 65грн/м2, від 7800грн

ПЛАНУВАЛЬНЕ ПРИБИРАННЯ (раз на тиждень):
- 40-60м2 — 40грн/м2, середнє 2000грн/тиж
- 70-90м2 — 35грн/м2, середнє 2800грн/тиж
- 100-140м2 — 25грн/м2, середнє 4800грн/тиж

ГЕНЕРАЛЬНЕ ПРИБИРАННЯ КУХНІ:
- до 6м2 — від 1800грн
- до 10м2 — від 2400грн
- до 20м2 — від 3100грн

ГЕНЕРАЛЬНЕ ПРИБИРАННЯ ВАННОЇ:
- до 5м2 — від 1300грн
- до 10м2 — від 1800грн
- до 20м2 — від 2600грн

НАША ХІМІЯ (Clinex + Karpax):

ЖИР / КУХНЯ / ГРИЛЬ:
- Clinex Гриль 5л — гриль, духовка, нагар. Наносиш, чекаєш 5-10 хв, змиваєш
- Clinex Фаст Гаст 5л — всі жирні поверхні: плита, витяжка, кахель на кухні. Швидка дія

САНВУЗОЛ / ВАННА:
- Clinex W3 Форте 10л — важка артилерія для занедбаних санвузлів. Вапняк, іржа, наліт
- Clinex W3 Актів Біо 1л — щоденна гігієна туалету і ванни
- Clinex W3 Мульті 1л — гель для санітарних кімнат, дезінфекція
- Clinex М3 Асід 1л — кислотний, для підлог і санітарних приміщень

СКЛО / ВІКНА:
- Clinex Профіт Глас 1л — концентрат для скла, розводиш водою
- Clinex Глас 1л — готовий засіб для скла, без розведення

ПІДЛОГИ:
- Clinex Вуд Панел 1л — ламінат і лакований паркет, без розводів
- Clinex Флорал Блаш 5л — універсальна підлога, приємний запах
- Clinex Ластріко 1л — тераццо і натуральний камінь

НЕРЖАВІЙКА:
- Clinex Шайн Стіл 650мл — полірування, прибирає відбитки пальців
- Clinex Гастро Стіл 1л — чищення нержавійки на кухні

ШВИ МІЖ ПЛИТКОЮ:
- Clinex W3 Фуга 0,5л — спеціально для швів. Наносиш щіткою, чекаєш, змиваєш

УНІВЕРСАЛЬНЕ:
- Clinex Блінк 1л — будь-які водостійкі поверхні
- Clinex Стронгер 0,75л — молочко для стійких забруднень без подряпин
- Clinex Анті-Спод 250мл — виведення плям

ХІМЧИСТКА КИЛИМІВ / М'ЯКИХ МЕБЛІВ (Karpax):
- Венус Вера 10кг — основний засіб для килимів і м'яких меблів
- Венус УльтраВайт 2 3кг — для світлих і білих поверхонь
- Форс 5кг — лужний плямовивідник, сильні плями
- Мультиспрей 5кг — лужний плямовивідник у спреї
- Оксімакс 5кг — кисневий плямовивідник, делікатні тканини
- Експерт 5кг — кислотний плямовивідник
- Крістал 1,25кг — килими, матраци, авто салони
- Рінза NEW 5кг — кислотний ополіскувач після хімчистки

ПАРФУМ:
- Парфум Вера 1л — фінальний акорд після прибирання

ЩО БРАТИ ПІД КОНКРЕТНЕ ЗАБРУДНЕННЯ:
- Іржа → Clinex W3 Форте
- Жир → Clinex Фаст Гаст або Clinex Гриль (якщо духовка)
- Вапняк/наліт → Clinex W3 Форте або М3 Асід
- Цвіль/пліснява → Clinex W3 Актів Біо + рукавички + маска!
- Шви між плиткою → Clinex W3 Фуга + щітка для швів
- Скло/вікна → Clinex Глас або Профіт Глас
- Ламінат/паркет → Clinex Вуд Панел
- Нержавійка → Clinex Шайн Стіл або Гастро Стіл
- Килими/дивани → Венус Вера + Крістал + Рінза NEW
- Загальне прибирання → Clinex Блінк або Флорал Блаш
- Плями → Clinex Анті-Спод або Форс або Оксімакс

СТАНДАРТНИЙ ІНВЕНТАР:
- Відро, швабра, мікрофібра х5, рукавички, губки, для кібатури баночка
- При високих стелях: драбина, телескопна швабра
- При хімчистці: пилосос з турбощіткою, пароочисник
- При мийці вікон: скловидалювач, мікрофібра для скла"""

# ──────────────────────────────────────────────────────────────────────────────
# БАЗА ДАНИХ
# ──────────────────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dialogs (
            id SERIAL PRIMARY KEY,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    cur.execute("CREATE INDEX IF NOT EXISTS dialogs_question_trgm ON dialogs USING GIN (question gin_trgm_ops)")
    conn.commit()
    cur.close()
    conn.close()

def save_dialog(question: str, answer: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO dialogs (question, answer) VALUES (%s, %s)", (question, answer))
    conn.commit()
    cur.close()
    conn.close()

def search_archive(query: str, limit: int = 3) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT question, answer, similarity(question, %s) AS sim
        FROM dialogs WHERE similarity(question, %s) > 0.15
        ORDER BY sim DESC LIMIT %s
    """, (query, query, limit))
    results = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in results]

# ──────────────────────────────────────────────────────────────────────────────
# СТИСНЕННЯ КОНТЕКСТУ
# ──────────────────────────────────────────────────────────────────────────────

MAX_HISTORY = 10
KEEP_RECENT = 4

def compress_history(history: list) -> list:
    if len(history) <= MAX_HISTORY:
        return history
    old = history[:-KEEP_RECENT]
    recent = history[-KEEP_RECENT:]
    old_text = "\n".join(
        f"{'Бригадир' if m['role'] == 'user' else 'Жора'}: {m['content']}"
        for m in old
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=300,
            messages=[{"role": "user", "content": (
                "Стисни цей робочий діалог в 2-3 речення. "
                "Збережи: про який об'єкт говорили, яка хімія/інвентар згадувались, "
                "які рішення прийняли. Без зайвих слів.\n\n" + old_text
            )}]
        )
        summary = resp.content[0].text.strip()
    except Exception:
        return recent
    return [{"role": "user", "content": f"[Контекст попереднього діалогу]: {summary}"}] + recent

# ──────────────────────────────────────────────────────────────────────────────
# СТАН ДІАЛОГУ
# ──────────────────────────────────────────────────────────────────────────────

DIALOG_TIMEOUT = 300
group_dialog = {"active": False, "last_time": 0, "history": []}

# ──────────────────────────────────────────────────────────────────────────────
# ЧЕКЛИСТ ЗАБРУДНЕНЬ
# ──────────────────────────────────────────────────────────────────────────────

CONTAMINATIONS = [
    ("🟡 Жир", "grease"), ("🔵 Вапняний наліт/камінь", "limestone"),
    ("🟤 Іржа", "rust"), ("⬛ Цвіль/пліснява", "mold"),
    ("🪟 Брудні вікна", "windows"), ("🍳 Плита/духовка/холодильник", "appliances"),
    ("🔲 Шви плитки", "tile_joints"), ("🧹 Складні плями", "stains"),
    ("👃 Неприємний запах", "smell"), ("🐾 Шерсть тварин", "pet_hair"),
    ("📏 Високі стелі", "high_ceiling"), ("🏗 Після ремонту", "after_repair"),
    ("💀 Запущений об'єкт", "neglected"), ("🛋 М'які меблі/килими", "soft_furniture"),
    ("💧 Немає води/світла", "no_utilities"), ("🌸 Потрібен парфум", "perfume"),
]

def checklist_keyboard(selected):
    keyboard = []
    for label, key in CONTAMINATIONS:
        mark = "✅ " if key in selected else ""
        keyboard.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"check_{key}")])
    keyboard.append([InlineKeyboardButton("Готово — отримати звіт", callback_data="check_done")])
    return InlineKeyboardMarkup(keyboard)

# ──────────────────────────────────────────────────────────────────────────────
# ФОРМА ЛІДА (крок за кроком)
# ──────────────────────────────────────────────────────────────────────────────

async def lead_form_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("📋 *Новий лід*\n\nІм'я клієнта:", parse_mode="Markdown")
    return LEAD_NAME

async def lead_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["lead_name"] = update.message.text.strip()
    await update.message.reply_text("📞 Телефон:")
    return LEAD_PHONE

async def lead_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["lead_phone"] = update.message.text.strip()
    await update.message.reply_text("💰 Сума (грн):")
    return LEAD_SUM

async def lead_sum(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["lead_sum"] = update.message.text.strip()
    await update.message.reply_text("👤 Хто працював?")
    return LEAD_WORKER

async def lead_worker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    worker = update.message.text.strip()
    name   = context.user_data.get("lead_name", "")
    phone  = context.user_data.get("lead_phone", "")
    amount = context.user_data.get("lead_sum", "")
    ok = add_lead(name, phone, amount, worker)
    if ok:
        await update.message.reply_text(
            f"✅ Записано!\n\n👤 {name}\n📞 {phone}\n💰 {amount} грн\n🔧 {worker}"
        )
    else:
        await update.message.reply_text("❌ Помилка запису. Перевір підключення до таблиці.")
    context.user_data.clear()
    return ConversationHandler.END

async def lead_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Скасовано.")
    context.user_data.clear()
    return ConversationHandler.END

# ──────────────────────────────────────────────────────────────────────────────
# ПАРСИНГ ШВИДКОГО ЗАПИСУ
# «жора, запиши ліда: Іван, +380..., 2500грн, Маша»
# ──────────────────────────────────────────────────────────────────────────────

def parse_quick_lead(text: str) -> dict | None:
    cleaned = re.sub(r"жора[,\s]+запиши\s+л[іi]да?\s*[:—\-]?\s*", "", text, flags=re.IGNORECASE).strip()
    parts = [p.strip() for p in cleaned.split(",")]
    if len(parts) < 4:
        return None
    return {"name": parts[0], "phone": parts[1], "amount": parts[2], "worker": ", ".join(parts[3:])}

# ──────────────────────────────────────────────────────────────────────────────
# ГОЛОВНИЙ ХЕНДЛЕР
# ──────────────────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        return

    text       = update.message.text or ""
    caption    = update.message.caption or ""
    has_photo  = bool(update.message.photo)
    text_lower = text.lower()

    trigger_zhora = "жора" in text_lower or "жора" in caption.lower()
    now = time.time()
    dialog_active = (now - group_dialog["last_time"]) < DIALOG_TIMEOUT

    if trigger_zhora:
        group_dialog["active"] = True
        group_dialog["last_time"] = now
    elif dialog_active:
        group_dialog["last_time"] = now

    if not trigger_zhora and not dialog_active and not has_photo:
        return

    # 1. ШВИДКИЙ ЗАПИС ЛІДА ─────────────────────────────────────────────────
    if trigger_zhora and re.search(r"запиши\s+л[іi]да?", text_lower):
        lead = parse_quick_lead(text)
        if lead:
            ok = add_lead(lead["name"], lead["phone"], lead["amount"], lead["worker"])
            msg = (
                f"✅ Лід записаний!\n\n👤 {lead['name']}\n📞 {lead['phone']}\n"
                f"💰 {lead['amount']} грн\n🔧 {lead['worker']}"
                if ok else "❌ Не вдалось записати. Перевір таблицю."
            )
        else:
            msg = (
                "Не зрозумів формат 🤔\n\n"
                "Пиши так:\n_Жора, запиши ліда: Іван, +380501234567, 2500грн, Маша_"
            )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # 2. ЗАПУСК ФОРМИ ────────────────────────────────────────────────────────
    if trigger_zhora and re.search(r"(нов(ий|ого)?\s+л[іi]д|форма|додай\s+л[іi]да?)", text_lower):
        await lead_form_start(update, context)
        return

    # 3. ПОШУК КЛІЄНТА ───────────────────────────────────────────────────────
    if trigger_zhora and re.search(r"(знайди|шукай|пошук|є\s+клієнт)", text_lower):
        query = re.sub(r"жора[,\s]*", "", text_lower)
        query = re.sub(r"(знайди|шукай|пошук|є\s+клієнт)[,\s]*", "", query).strip()
        if not query:
            await update.message.reply_text("Що шукати? Напиши ім'я або телефон.")
            return
        results = search_lead(query)
        if not results:
            await update.message.reply_text(f"Нічого не знайшов по «{query}» 🤷")
        else:
            lines = [f"🔍 Знайдено: {len(results)}\n{'─'*22}"]
            for r in results:
    lines = [f"🔍 Знайдено: {len(results)}\n" + "─"*22]
            for r in results:
                name = r.get("Ім'я", "")
                lines.append(
                    f"📅 {r.get('Дата','')}\n"
                    f"👤 {name}\n"
                    f"📞 {r.get('Телефон','')}\n"
                    f"💰 {r.get('Сума (грн)','')}\n"
                    f"🔧 {r.get('Хто працював','')}\n"
                    + "─"*22
                )
            await update.message.reply_text("\n".join(lines))
            await update.message.reply_text("\n".join(lines))
        return

    # 4. СТАТИСТИКА ──────────────────────────────────────────────────────────
    if trigger_zhora and re.search(r"(стат|скільки|підсумок|звіт по лідам|доход)", text_lower):
        stats = get_stats()
        if not stats:
            await update.message.reply_text("Таблиця порожня або помилка підключення.")
            return
        top = "\n".join(f"  {i+1}. {w} — {c} замовлень" for i, (w, c) in enumerate(stats["top_workers"]))
        msg = (
            f"📊 *Статистика лідів*\n\n"
            f"📋 Всього: {stats['total']}\n"
            f"💰 Сума: {stats['sum']:,} грн\n"
            f"📈 Середній чек: {stats['avg']:,} грн\n\n"
            f"🏆 Топ працівники:\n{top}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # 5. ФОТО ────────────────────────────────────────────────────────────────
    if has_photo and (trigger_zhora or dialog_active or caption):
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")
        prompt = caption if caption else (
            "Проаналізуй це фото з точки зору клінінгу. "
            "Що тут забруднено? Які засоби і інвентар потрібні? "
            "Використовуй тільки хімію Clinex та Karpax."
        )
        group_dialog["last_time"] = now
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=800, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                    {"type": "text", "text": prompt}
                ]}]
            )
            reply = response.content[0].text
            group_dialog["history"].append({"role": "assistant", "content": reply})
            save_dialog(prompt, reply)
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"Помилка: {e}")
        return

    # 6. ЧЕКЛИСТ ОГЛЯДУ ──────────────────────────────────────────────────────
if trigger_zhora and re.search(
    r"(огляд|обьект|об.єкт|объект|осмотр|що брати|що взяти|збери|"
    r"дай кнопки|покажи кнопки|на уборку|на прибирання|збір хімії|що нести|"
    r"підготуй список|що готувати|їдемо на|виїзд на|виїзд завтра)",
    text_lower
):
        context.user_data["checklist"] = []
        await update.message.reply_text("Огляд об'єкту — відмічай що є:", reply_markup=checklist_keyboard([]))
        return

    # 7. ЗВИЧАЙНИЙ ДІАЛОГ ────────────────────────────────────────────────────
    if trigger_zhora or dialog_active:
        clean_text = re.sub(r"жора[,\s]*", "", text_lower).strip()
        if not clean_text:
            return

        archive_hits = search_archive(clean_text)
        archive_context = ""
        if archive_hits:
            examples = "\n".join(
                f"Питання: {h['question']}\nВідповідь: {h['answer']}" for h in archive_hits
            )
            archive_context = f"\n\n[Схожі кейси з архіву]:\n{examples}"

        group_dialog["history"] = compress_history(group_dialog["history"])
        group_dialog["history"].append({"role": "user", "content": clean_text + archive_context})

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=800, system=SYSTEM_PROMPT,
                messages=group_dialog["history"]
            )
            reply = response.content[0].text
            group_dialog["history"].append({"role": "assistant", "content": reply})
            save_dialog(clean_text, reply)
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"Помилка: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# ХЕНДЛЕР ЧЕКЛИСТА
# ──────────────────────────────────────────────────────────────────────────────

async def handle_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in WHITELIST:
        return

    if "checklist" not in context.user_data:
        context.user_data["checklist"] = []
    selected = context.user_data["checklist"]

    if query.data == "check_done":
        if not selected:
            await query.edit_message_text("Нічого не відмічено. Об'єкт чистий?")
            return
        labels = {key: label for label, key in CONTAMINATIONS}
        selected_labels = [labels[k] for k in selected if k in labels]
        report = "ЗВІТ ОГЛЯДУ\n\nЗнайдено:\n" + "".join(f"- {l}\n" for l in selected_labels)
        prompt = (
            f"Бригадир відмітив забруднення: {', '.join(selected_labels)}. "
            "Склади список що взяти з нашої хімії Clinex та Karpax, "
            "інвентар, і короткі поради по роботі з кожним забрудненням."
        )
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=800, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            reply = response.content[0].text
            save_dialog(prompt, reply)
            await query.edit_message_text(report + "\n" + reply)
        except Exception as e:
            await query.edit_message_text(f"Помилка: {e}")
        context.user_data["checklist"] = []
        return

    key = query.data.replace("check_", "")
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    context.user_data["checklist"] = selected
    await query.edit_message_reply_markup(reply_markup=checklist_keyboard(selected))

# ──────────────────────────────────────────────────────────────────────────────
# ЗАПУСК
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    lead_conv = ConversationHandler(
        entry_points=[],
        states={
            LEAD_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, lead_name)],
            LEAD_PHONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, lead_phone)],
            LEAD_SUM:    [MessageHandler(filters.TEXT & ~filters.COMMAND, lead_sum)],
            LEAD_WORKER: [MessageHandler(filters.TEXT & ~filters.COMMAND, lead_worker)],
        },
        fallbacks=[MessageHandler(filters.Regex("(?i)скасувати|cancel"), lead_cancel)],
        per_chat=False,
        per_user=True,
    )

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(lead_conv)
    app.add_handler(CallbackQueryHandler(handle_checklist, pattern="^check_"))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.run_polling()
