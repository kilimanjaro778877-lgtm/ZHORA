import os
import base64
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("SHOHA_TOKEN")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

WHITELIST = [8273711154, 869727778, 6815670488, 8548088353]

SYSTEM_PROMPT = """Спілкуєшся українською та суржиком — як свій хлопець в команді. 
Розумієш російську але відповідаєш українською/суржиком.
Якщо хтось матюкається — можеш відповісти з матюком але рідко і до місця 😄.

ЦІНИ НА ПОСЛУГИ:
Генеральне прибирання: 40-60м² від 4000грн, 70-90м² від 6000грн, 100-140м² від 8400грн
Підтримуюче: 40-60м² від 2250грн, 70-90м² від 4000грн, 100-140м² від 3000грн
Планувальне: 40-60м² від 2000грн/тиж, 70-90м² від 2800грн/тиж, 100-140м² від 4800грн/тиж
Генеральне кухні: до 6м² від 1800грн, до 10м² від 2400грн, до 20м² від 3100грн
Генеральне ванної: до 5м² від 1300грн, до 10м² від 1800грн, до 20м² від 2600грн
Хімчистка дивану: 2-місний від 1100грн, 3-місний від 1650грн, 4-місний від 2200грн, кутовий від 2400грн, модульний від 2700грн
Хімчистка матраса: дитячий від 300грн, односпальний від 550грн, полуторний від 800грн, двоспальний від 1100грн
Крісло від 400грн, стілець від 200грн, автосидіння 550грн/місце, килим від 160грн/м²
Мийка вікон: 80грн/м²
Мінімальний виїзд: 1500грн

ЗАСОБИ ПО ЗАБРУДНЕННЯМ:
- Іржа → Cillit Bang Rust або Санокс
- Жир → знежирювач, AOS концентрат
- Вапняк/наліт → Domestos, Тофіфан, лимонна кислота
- Цвіль/пліснява → Білизна, Антиплісень (рукавички + маска обов'язково!)
- Шви між плиткою → щітка для швів + знежирювач або пароочисник
- Загальне прибирання → універсальний засіб, мікрофібра

ІНВЕНТАР:
- Стандартний набір: відро, швабра, мікрофібра х5, рукавички, губки
- Додатково при високих стелях: драбина, телескопна швабра
- При хімчистці: пилосос з турбощіткою, пароочисник
- При мийці вікон: скловидалювач, мікрофібра для скла, засіб для скла"""

CONTAMINATIONS = [
    ("🟤 Іржа", "rust"),
    ("🟡 Жир", "grease"),
    ("🔵 Вапняк/наліт", "limestone"),
    ("⬛ Цвіль/пліснява", "mold"),
    ("📏 Високі стелі", "high_ceiling"),
    ("🔲 Шви між плиткою", "tile_joints"),
    ("🌸 Потрібен парфум", "perfume"),
    ("🚽 Проблемний санвузол", "bathroom"),
    ("🍳 Проблемна кухня", "kitchen"),
    ("🪟 Брудні вікна", "windows"),
]

def checklist_keyboard(selected):
    keyboard = []
    for label, key in CONTAMINATIONS:
        mark = "✅ " if key in selected else ""
        keyboard.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"check_{key}")])
    keyboard.append([InlineKeyboardButton("📋 Готово — отримати звіт", callback_data="check_done")])
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

    # Чекліст огляду
    if trigger_shoha and ("огляд" in text.lower() or "обьект" in text.lower() or "об'єкт" in text.lower()):
        context.user_data["checklist"] = []
        await update.message.reply_text(
            "🔍 *Огляд об'єкту*\n\nВідмічай що є на об'єкті:",
            parse_mode="Markdown",
            reply_markup=checklist_keyboard([])
        )
        return

    # Фото — аналіз
    if has_photo:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")
        prompt = caption if caption else "Проаналізуй це фото з точки зору клінінгу. Що тут забруднено? Які засоби і інвентар потрібні?"

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
        await update.message.reply_text(response.content[0].text)
        return

    # Звичайне питання до Шохи
    if trigger_shoha:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}]
        )
        await update.message.reply_text(response.content[0].text)

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
            await query.edit_message_text("❗ Нічого не відмічено. Об'єкт чистий? 😄")
            return

        # Формуємо звіт
        labels = {key: label for label, key in CONTAMINATIONS}
        selected_labels = [labels[k] for k in selected if k in labels]
        report = "📋 *ЗВІТ ОГЛЯДУ ОБ'ЄКТУ*\n\n"
        report += "🔴 Виявлені забруднення:\n"
        for label in selected_labels:
            report += f"  • {label}\n"

        # Питаємо Claude що взяти
        prompt = f"Бригадир відмітив такі забруднення на об'єкті: {', '.join(selected_labels)}. Складіть точний список що взяти із собою (засоби, інвентар), та дайте короткі поради по роботі з цими забрудненнями."

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )

        await query.edit_message_text(
            report + "\n" + response.content[0].text,
            parse_mode="Markdown"
        )
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