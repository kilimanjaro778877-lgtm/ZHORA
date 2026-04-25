import os
import base64
import time
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("SHOHA_TOKEN")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

WHITELIST = [8273711154, 869727778, 6815670488, 8548088353]

SYSTEM_PROMPT = """Ти — Шоха, досвідчений фахівець клінінгової компанії з 10+ роками практики.
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

CONTAMINATIONS = [
    ("Іржа", "rust"),
    ("Жир", "grease"),
    ("Вапняк/наліт", "limestone"),
    ("Цвіль/пліснява", "mold"),
    ("Високі стелі", "high_ceiling"),
    ("Шви між плиткою", "tile_joints"),
    ("Потрібен парфум", "perfume"),
    ("Проблемний санвузол", "bathroom"),
    ("Проблемна кухня", "kitchen"),
    ("Брудні вікна", "windows"),
]

group_dialog = {
    "active": False,
    "last_time": 0,
    "history": []
}

DIALOG_TIMEOUT = 300

def checklist_keyboard(selected):
    keyboard = []
    for label, key in CONTAMINATIONS:
        mark = "OK " if key in selected else ""
        keyboard.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"check_{key}")])
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

    trigger_shoha = "шоха" in text.lower() or "шоха" in caption.lower()

    now = time.time()
    dialog_active = (now - group_dialog["last_time"]) < DIALOG_TIMEOUT

    if trigger_shoha:
        group_dialog["active"] = True
        group_dialog["last_time"] = now
    elif dialog_active:
        group_dialog["last_time"] = now

    if not trigger_shoha and not dialog_active and not has_photo:
        return

    if has_photo and (trigger_shoha or dialog_active or caption):
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")
        prompt = caption if caption else "Проаналізуй це фото з точки зору клінінгу. Що тут забруднено? Які засоби і інвентар потрібні? Використовуй тільки хімію Clinex та Karpax."

        group_dialog["last_time"] = now

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=800,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )
            reply = response.content[0].text
            group_dialog["history"].append({"role": "assistant", "content": reply})
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"Помилка: {e}")
        return

    if trigger_shoha and ("огляд" in text.lower() or "обьект" in text.lower() or "об'єкт" in text.lower()):
        context.user_data["checklist"] = []
        await update.message.reply_text(
            "Огляд об'єкту — відмічай що є:",
            reply_markup=checklist_keyboard([])
        )
        return

    if trigger_shoha or dialog_active:
        clean_text = text.lower().replace("шоха,", "").replace("шоха", "").strip()
        if not clean_text:
            return

        group_dialog["history"].append({"role": "user", "content": clean_text})

        if len(group_dialog["history"]) > 10:
            group_dialog["history"] = group_dialog["history"][-10:]

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=800,
                system=SYSTEM_PROMPT,
                messages=group_dialog["history"]
            )
            reply = response.content[0].text
            group_dialog["history"].append({"role": "assistant", "content": reply})
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"Помилка: {e}")

async def handle_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id not in WHITELIST:
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

        report = "ЗВІТ ОГЛЯДУ\n\nЗнайдено:\n"
        for label in selected_labels:
            report += f"- {label}\n"

        prompt = f"Бригадир відмітив забруднення: {', '.join(selected_labels)}. Склади список що взяти з нашої хімії Clinex та Karpax, інвентар, і короткі поради по роботі з кожним забрудненням."

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=800,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            await query.edit_message_text(report + "\n" + response.content[0].text)
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

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CallbackQueryHandler(handle_checklist, pattern="^check_"))
app.add_handler(MessageHandler(filters.ALL, handle_message))
app.run_polling()
