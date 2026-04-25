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
– підказувати, що брати на об'єкт (хімія, техніка, інвентар)
– давати чіткий план роботи по порядку
– оцінювати складність, час і об'єм робіт
– попереджати про ризики і типові помилки
– підстраховувати команду, якщо щось забули або не врахували
– оптимізувати процес, щоб було швидко і якісно
Стиль спілкування:
– українська + суржик (живий, розмовний стиль)
– коротко, чітко, по справі
– без офіціозу, без "води"
– можеш жартувати, але без клоунади
– якщо в чаті використовують мат — можеш іноді відповісти в тому ж стилі, але доречно і без перегибів
Як ти мислиш:
– як бригадир з великим досвідом
– завжди думаєш наперед: що може піти не так
– орієнтований на результат, швидкість і якість
– не даєш зайвих порад — тільки те, що реально потрібно
Формат відповідей:
– короткі повідомлення
– якщо потрібно — списки або чіткі кроки
– без довгих пояснень
Ти не обмежуєш себе в спілкуванні, говориш природно, як жива людина з досвідом. Головне — користь для команди, ясність і результат.

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
- Цвіль/пліснява → Білизна, Антиплісень (рукавички + маска!)
- Шви між плиткою → щітка для швів + знежирювач або пароочисник
- Загальне → універсальний засіб, мікрофібра

ІНВЕНТАР:
- Стандартний набір: відро, швабра, мікрофібра х5, рукавички, губки
- При високих стелях: драбина, телескопна швабра
- При хімчистці: пилосос з турбощіткою, пароочисник
- При мийці вікон: скловидалювач, мікрофібра для скла, засіб для скла"""


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
- Цвіль/пліснява → Білизна, Антиплісень (рукавички + маска!)
- Шви між плиткою → щітка для швів + знежирювач або пароочисник
- Загальне → універсальний засіб, мікрофібра

ІНВЕНТАР:
- Стандартний набір: відро, швабра, мікрофібра х5, рукавички, губки
- При високих стелях: драбина, телескопна швабра
- При хімчистці: пилосос з турбощіткою, пароочисник
- При мийці вікон: скловидалювач, мікрофібра для скла, засіб для скла"""

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
- Цвіль/пліснява → Білизна, Антиплісень (рукавички + маска!)
- Шви між плиткою → щітка для швів + знежирювач або пароочисник
- Загальне → універсальний засіб, мікрофібра

ІНВЕНТАР:
- Стандартний набір: відро, швабра, мікрофібра х5, рукавички, губки
- При високих стелях: драбина, телескопна швабра
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

# Глобальний стан діалогу для групи
group_dialog = {
    "active": False,
    "last_time": 0,
    "history": []
}

DIALOG_TIMEOUT = 300  # 5 хвилин

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

    # Перевіряємо активний діалог
    now = time.time()
    dialog_active = (now - group_dialog["last_time"]) < DIALOG_TIMEOUT

    if trigger_shoha:
        group_dialog["active"] = True
        group_dialog["last_time"] = now
    elif not dialog_active:
        group_dialog["active"] = False

    # Якщо не Шоха і діалог не активний — мовчимо
    if not trigger_shoha and not dialog_active and not has_photo:
        return

    # Фото — аналіз завжди якщо є підпис або активний діалог
    if has_photo and (trigger_shoha or dialog_active or caption):
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")
        prompt = caption if caption else "Проаналізуй це фото з точки зору клінінгу. Що тут забруднено? Які засоби і інвентар потрібні?"

        group_dialog["last_time"] = now

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
        return

    # Чекліст
    if trigger_shoha and ("огляд" in text.lower() or "обьект" in text.lower() or "об'єкт" in text.lower()):
        context.user_data["checklist"] = []
        await update.message.reply_text(
            "🔍 *Огляд об'єкту*\n\nВідмічай що є на об'єкті:",
            parse_mode="Markdown",
            reply_markup=checklist_keyboard([])
        )
        return

    # Звичайне повідомлення — додаємо в історію
    if trigger_shoha or dialog_active:
        clean_text = text.replace("Шоха,", "").replace("шоха,", "").replace("Шоха", "").replace("шоха", "").strip()
        if not clean_text:
            return

        group_dialog["history"].append({"role": "user", "content": clean_text})
        group_dialog["last_time"] = now

        # Обмежуємо історію до 10 повідомлень
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
            print(f"Помилка: {e}")
            await update.message.reply_text("Вибач, щось пішло не так 😅")

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

        labels = {key: label for label, key in CONTAMINATIONS}
        selected_labels = [labels[k] for k in selected if k in labels]
        report = "📋 *ЗВІТ ОГЛЯДУ ОБ'ЄКТУ*\n\n"
        report += "🔴 Виявлені забруднення:\n"
        for label in selected_labels:
            report += f"  • {label}\n"

        prompt = f"Бригадир відмітив такі забруднення на об'єкті: {', '.join(selected_labels)}. Склади точний список що взяти із собою (засоби, інвентар), та дай короткі поради по роботі з цими забрудненнями. Відповідай як свій хлопець, по-братськи."

        try:
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
