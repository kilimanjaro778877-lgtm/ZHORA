import os
import base64
import time
import json
import re
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("SHOHA_TOKEN")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_KEY")
GOOGLE_CREDS   = os.environ.get("GOOGLE_CREDS_JSON")
SHEET_ID       = os.environ.get("SHEET_ID")

_required_env = {
    "SHOHA_TOKEN": TELEGRAM_TOKEN,
    "ANTHROPIC_KEY": ANTHROPIC_KEY,
    "GOOGLE_CREDS_JSON": GOOGLE_CREDS,
    "SHEET_ID": SHEET_ID,
}
_missing = [name for name, value in _required_env.items() if not value]
if _missing:
    raise SystemExit("Не задані обов'язкові env-vars: " + ", ".join(_missing))

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

WHITELIST = [8273711154, 869727778, 6815670488, 8548088353]

SYSTEM_PROMPT = """Ти — Жора, досвідчений фахівець клінінгової компанії з 10+ роками практики.
Працюєш у внутрішній робочій групі з бригадирами та менеджерами. Ти частина команди, а не бот. Спілкуєшся як свій, але мислиш як професіонал, який відповідає за результат.

Твоя задача:
- підказувати, що брати на об'єкт (хімія, техніка, інвентар)
- давати чіткий план роботи по порядку
- оцінювати складність, час і об'єм робіт
- попереджати про ризики і типові помилки
- підстраховувати команду, якщо щось забули або не врахували
- оптимізувати процес, щоб було швидко і якісно

Мова спілкування:
- Якщо пишуть українською — відповідай українською + суржик
- Якщо пишуть російською — відповідай російською, по-свойски
- Коротко, чітко, по справі
- Без офіціозу і "води"
- Можеш жартувати, але без клоунади
- Якщо використовують мат — можеш іноді відповісти в тому ж стилі, але доречно

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
- 1 посадкове місце дивану — 550 грн
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
- Clinex Гриль 5л — гриль, духовка, нагар
- Clinex Фаст Гаст 5л — плита, витяжка, кахель

САНВУЗОЛ / ВАННА:
- Clinex W3 Форте 10л — вапняк, іржа, наліт, занедбані санвузли
- Clinex W3 Актів Біо 1л — щоденна гігієна
- Clinex W3 Мульті 1л — дезінфекція
- Clinex М3 Асід 1л — кислотний, підлоги і санвузли

СКЛО / ВІКНА:
- Clinex Профіт Глас 1л — концентрат, розводиш водою
- Clinex Глас 1л — готовий, без розведення

ПІДЛОГИ:
- Clinex Вуд Панел 1л — ламінат і паркет
- Clinex Флорал Блаш 5л — універсальна підлога
- Clinex Ластріко 1л — тераццо і камінь

НЕРЖАВІЙКА:
- Clinex Шайн Стіл 650мл — полірування
- Clinex Гастро Стіл 1л — кухонна нержавійка

ШВИ МІЖ ПЛИТКОЮ:
- Clinex W3 Фуга 0,5л — щітка + чекати + змити

УНІВЕРСАЛЬНЕ:
- Clinex Блінк 1л — будь-які поверхні
- Clinex Стронгер 0,75л — стійкі забруднення без подряпин
- Clinex Анті-Спод 250мл — плями

ХІМЧИСТКА КИЛИМІВ / М'ЯКИХ МЕБЛІВ (Karpax):
- Венус Вера 10кг — основний для килимів і меблів
- Венус УльтраВайт 2 3кг — світлі поверхні
- Форс 5кг — сильні плями
- Мультиспрей 5кг — спрей для плям
- Оксімакс 5кг — делікатні тканини
- Експерт 5кг — кислотний плямовивідник
- Крістал 1,25кг — килими, матраци, авто
- Рінза NEW 5кг — ополіскувач після хімчистки

ПАРФУМ:
- Парфум Вера 1л — фінальний акорд

ЩО БРАТИ ПІД ЗАБРУДНЕННЯ:
- Іржа → W3 Форте
- Жир → Фаст Гаст або Гриль (духовка)
- Вапняк/наліт → W3 Форте або М3 Асід
- Цвіль → Актів Біо + рукавички + маска!
- Шви плитки → W3 Фуга + щітка
- Скло/вікна → Глас або Профіт Глас
- Ламінат/паркет → Вуд Панел
- Нержавійка → Шайн Стіл або Гастро Стіл
- Килими/дивани → Венус Вера + Крістал + Рінза NEW
- Загальне → Блінк або Флорал Блаш
- Плями → Анті-Спод або Форс або Оксімакс

СТАНДАРТНИЙ ІНВЕНТАР:
- Відро, швабра, мікрофібра х5, рукавички, губки
- Високі стелі: драбина, телескопна швабра
- Хімчистка: пилосос з турбощіткою, пароочисник
- Вікна: скловидалювач, мікрофібра для скла"""


# ── Назви місяців для автоматичного пошуку аркуша ──
MONTH_NAMES = {
    1:  ["січень", "январь", "january"],
    2:  ["лютий", "февраль", "february"],
    3:  ["березень", "март", "march"],
    4:  ["квітень", "апрель", "april"],
    5:  ["травень", "май", "may"],
    6:  ["червень", "июнь", "june"],
    7:  ["липень", "июль", "july"],
    8:  ["серпень", "август", "august"],
    9:  ["вересень", "сентябрь", "september"],
    10: ["жовтень", "октябрь", "october"],
    11: ["листопад", "ноябрь", "november"],
    12: ["грудень", "декабрь", "december"],
}


def get_gc():
    creds_dict = json.loads(GOOGLE_CREDS)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def get_ws(month=None):
    """
    Знаходить аркуш по місяцю.
    month — число 1-12, якщо None — бере поточний місяць.
    """
    gc = get_gc()
    sh = gc.open_by_key(SHEET_ID)
    if month is None:
        month = datetime.now().month
    keywords = MONTH_NAMES.get(month, [])
    for ws in sh.worksheets():
        ws_lower = ws.title.lower()
        for kw in keywords:
            if kw in ws_lower:
                return ws
    return sh.sheet1


def parse_date(text_lower):
    """Парсить дату з тексту. Повертає (date_str, month)"""
    if re.search(r"завтра|tomorrow|зафтра", text_lower):
        tomorrow = datetime.now() + timedelta(days=1)
        return tomorrow.strftime("%d.%m"), tomorrow.month
    match = re.search(r"на\s+(\d{1,2})[.](\d{2})", text_lower)
    if match:
        day = match.group(1).zfill(2)
        mon = match.group(2)
        return day + "." + mon, int(mon)
    return None, datetime.now().month


def write_lead(name, phone, amount=None, target_date=None, month=None):
    try:
        ws = get_ws(month)
        target = target_date if target_date else datetime.now().strftime("%d.%m")

        col_a = ws.col_values(1)
        row_num = None
        for i, val in enumerate(col_a):
            if str(val).strip() == target:
                row_num = i + 1
                break

        if not row_num:
            return False, "Дату " + target + " не знайшов в таблиці 🤷"

        ws.update_cell(row_num, 2, name)
        ws.update_cell(row_num, 3, phone)
        if amount:
            clean_amount = re.sub(r"[^\d.]", "", amount.replace(",", "."))
            if clean_amount:
                ws.update_cell(row_num, 4, clean_amount)
        return True, target

    except Exception as e:
        print("Sheets error: " + str(e))
        return False, str(e)


def get_stats():
    try:
        ws = get_ws()
        all_vals = ws.get_all_values()
        total = 0
        total_sum = 0
        for row in all_vals[1:]:
            if len(row) > 1 and str(row[1]).strip():
                total += 1
                if len(row) > 3:
                    num = re.sub(r"[^\d.]", "", str(row[3]).replace(",", "."))
                    try:
                        total_sum += float(num)
                    except Exception:
                        pass
        return {
            "total": total,
            "sum": int(total_sum),
            "avg": int(total_sum // total) if total else 0
        }
    except Exception as e:
        print("Stats error: " + str(e))
        return {}


def search_client(query):
    try:
        gc = get_gc()
        sh = gc.open_by_key(SHEET_ID)
        q = query.lower().strip()
        results = []
        for ws in sh.worksheets():
            all_vals = ws.get_all_values()
            for row in all_vals[1:]:
                name = str(row[1]).lower() if len(row) > 1 else ""
                phone = str(row[2]) if len(row) > 2 else ""
                date = str(row[0]) if len(row) > 0 else ""
                amount = str(row[3]) if len(row) > 3 else ""
                if q in name or q in phone:
                    results.append({
                        "date": date,
                        "sheet": ws.title,
                        "name": row[1] if len(row) > 1 else "",
                        "phone": phone,
                        "amount": amount
                    })
        return results[-10:]
    except Exception as e:
        print("Search error: " + str(e))
        return []


DIALOG_TIMEOUT = 300
group_dialog = {"active": False, "last_time": 0, "history": []}
lead_form_state = {}

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
        keyboard.append([InlineKeyboardButton(mark + label, callback_data="check_" + key)])
    keyboard.append([InlineKeyboardButton("Готово — отримати звіт", callback_data="check_done")])
    return InlineKeyboardMarkup(keyboard)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        return

    text = update.message.text or ""
    caption = update.message.caption or ""
    has_photo = bool(update.message.photo)
    text_lower = text.lower()

    trigger_zhora = "жора" in text_lower or "жора" in caption.lower()
    now = time.time()
    dialog_active = (now - group_dialog["last_time"]) < DIALOG_TIMEOUT

    if trigger_zhora:
        group_dialog["active"] = True
        group_dialog["last_time"] = now
    elif dialog_active:
        group_dialog["last_time"] = now

    # ── Форма ліда крок за кроком ──
    if user_id in lead_form_state:
        step = lead_form_state[user_id]["step"]
        if step == "name":
            lead_form_state[user_id]["name"] = text.strip()
            lead_form_state[user_id]["step"] = "phone"
            await update.message.reply_text("📞 Телефон:")
            return
        elif step == "phone":
            lead_form_state[user_id]["phone"] = text.strip()
            lead_form_state[user_id]["step"] = "amount"
            await update.message.reply_text("💰 Сума замовлення:")
            return
        elif step == "amount":
            lead_form_state[user_id]["amount"] = text.strip()
            lead_form_state[user_id]["step"] = "confirm"
            data = lead_form_state[user_id]
            date_label = data.get("date") or datetime.now().strftime("%d.%m")
            await update.message.reply_text(
                "Записую на " + date_label + ":\n"
                "👤 " + data["name"] + "\n"
                "📞 " + data["phone"] + "\n"
                "💰 " + data["amount"] + "\n\nВсе вірно? (так/ні)"
            )
            return
        elif step == "confirm":
            if any(w in text_lower for w in ["так", "да", "ок", "ok", "yes", "вірно", "верно"]):
                data = lead_form_state.pop(user_id)
                ok, result = write_lead(
                    data["name"], data["phone"],
                    data.get("amount"), data.get("date"), data.get("month")
                )
                if ok:
                    await update.message.reply_text("✅ Записано на " + result + "!")
                else:
                    await update.message.reply_text("❌ " + result)
            else:
                lead_form_state.pop(user_id)
                await update.message.reply_text("Скасовано.")
            return

    if not trigger_zhora and not dialog_active and not has_photo:
        return

    # ── Швидкий запис ліда ──
    if trigger_zhora and re.search(r"запиши\s+л[іiи]да?|записать\s+лид|запиши\s+лида", text_lower):
        target_date, month = parse_date(text_lower)
        cleaned = re.sub(r"жора[,\s]*", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"запиши\s+л[іiи]да?\s*(на\s+(завтра|tomorrow|зафтра|\d{1,2}[.]\d{2}))?\s*[:—\-]?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"записать\s+лид[а]?\s*(на\s+(завтра|tomorrow|зафтра|\d{1,2}[.]\d{2}))?\s*[:—\-]?\s*", "", cleaned, flags=re.IGNORECASE)
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]

        if len(parts) >= 2:
            name = parts[0]
            phone = parts[1]
            amount = parts[2] if len(parts) >= 3 else None
            ok, result = write_lead(name, phone, amount, target_date, month)
            if ok:
                msg = "✅ Записано!\n\n📅 " + result + "\n👤 " + name + "\n📞 " + phone
                if amount:
                    clean_a = re.sub(r"[^\d.]", "", amount)
                    if clean_a:
                        msg += "\n💰 " + clean_a + " грн"
                await update.message.reply_text(msg)
            else:
                await update.message.reply_text("❌ " + result)
        else:
            await update.message.reply_text(
                "Формат:\n"
                "_Жора, запиши ліда: Іван, 0660123456, 2700_\n"
                "_Жора, запиши ліда на завтра: Іван, 0660123456, 2700_\n"
                "_Жора, запиши ліда на 30.05: Іван, 0660123456, 2700_",
                parse_mode="Markdown"
            )
        return

    # ── Форма ліда ──
    if trigger_zhora and re.search(r"нов(ий|ого)?\s+л[іiи]д|новый\s+лид|додай\s+л[іiи]да?|добавь\s+лид|форма", text_lower):
        target_date, month = parse_date(text_lower)
        lead_form_state[user_id] = {"step": "name", "date": target_date, "month": month}
        date_label = target_date or datetime.now().strftime("%d.%m")
        await update.message.reply_text("📋 Новий лід на " + date_label + "\n\nІм'я клієнта:")
        return

    # ── Пошук ──
    if trigger_zhora and re.search(r"знайди|шукай|найди|поищи", text_lower):
        query = re.sub(r"жора[,\s]*", "", text_lower)
        query = re.sub(r"(знайди|шукай|найди|поищи)[,\s]*", "", query).strip()
        results = search_client(query)
        if not results:
            await update.message.reply_text("Нічого не знайшов по «" + query + "» 🤷")
        else:
            lines = ["🔍 Знайдено: " + str(len(results)) + "\n" + "─" * 20]
            for r in results:
                lines.append(
                    "📅 " + r["date"] + " (" + r["sheet"] + ")\n"
                    "👤 " + r["name"] + "\n"
                    "📞 " + r["phone"] + "\n"
                    "💰 " + r["amount"] + "\n"
                    + "─" * 20
                )
            await update.message.reply_text("\n".join(lines))
        return

    # ── Статистика ──
    if trigger_zhora and re.search(r"стат|скільки|сколько|підсумок|итог|доход", text_lower):
        stats = get_stats()
        if not stats:
            await update.message.reply_text("Таблиця порожня або помилка підключення.")
            return
        await update.message.reply_text(
            "📊 *Статистика*\n\n"
            "📋 Всього клієнтів: " + str(stats["total"]) + "\n"
            "💰 Загальна сума: " + str(stats["sum"]) + " грн\n"
            "📈 Середній чек: " + str(stats["avg"]) + " грн",
            parse_mode="Markdown"
        )
        return

    # ── Фото ──
    if has_photo and (trigger_zhora or dialog_active or caption):
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")
        prompt = caption if caption else "Проаналізуй це фото з точки зору клінінгу. Що тут забруднено? Які засоби і інвентар потрібні? Використовуй тільки хімію Clinex та Karpax."
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
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text("Помилка: " + str(e))
        return

    # ── Чеклист ──
    if trigger_zhora and re.search(
        r"(огляд|обьект|об.єкт|объект|осмотр|що брати|що взяти|збери|"
        r"дай кнопки|покажи кнопки|на уборку|на прибирання|що нести|"
        r"їдемо на|виїзд|выезд|что брать|что взять|собери)",
        text_lower
    ):
        context.user_data["checklist"] = []
        await update.message.reply_text("Огляд об'єкту — відмічай що є:", reply_markup=checklist_keyboard([]))
        return

    # ── Звичайний діалог ──
    if trigger_zhora or dialog_active:
        clean_text = re.sub(r"жора[,\s]*", "", text_lower).strip()
        if not clean_text:
            return
        group_dialog["history"].append({"role": "user", "content": clean_text})
        if len(group_dialog["history"]) > 10:
            group_dialog["history"] = group_dialog["history"][-10:]
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=800, system=SYSTEM_PROMPT,
                messages=group_dialog["history"]
            )
            reply = response.content[0].text
            group_dialog["history"].append({"role": "assistant", "content": reply})
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text("Помилка: " + str(e))


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
        report = "ЗВІТ ОГЛЯДУ\n\nЗнайдено:\n" + "".join("- " + l + "\n" for l in selected_labels)
        prompt = "Бригадир відмітив забруднення: " + ", ".join(selected_labels) + ". Склади список що взяти з нашої хімії Clinex та Karpax, інвентар, і короткі поради."
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=800, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            await query.edit_message_text(report + "\n" + response.content[0].text)
        except Exception as e:
            await query.edit_message_text("Помилка: " + str(e))
        context.user_data["checklist"] = []
        return
    key = query.data.replace("check_", "")
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    context.user_data["checklist"] = selected
    await query.edit_message_reply_markup(reply_markup=checklist_keyboard(selected))


app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CallbackQueryHandler(handle_checklist, pattern="^check_"))
app.add_handler(MessageHandler(filters.ALL, handle_message))
app.run_polling()
