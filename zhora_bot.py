"""
Модуль для Жоры: автоматичне створення нового листа щомісяця
Підключи в основний файл бота (zhora.py або main.py)

ВСТАНОВИТИ:
    pip install gspread google-auth apscheduler

ПІДКЛЮЧИТИ В БОТА:
    from month_sheet import setup_scheduler
    ...
    if __name__ == "__main__":
        setup_scheduler(application)
        application.run_polling()
"""

import gspread
import calendar
import logging
from datetime import datetime
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os

logger = logging.getLogger(__name__)

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────
SHEET_ID    = "1_R7j0gmV7n8wQtrB_131iP3HiNAPA8_YiEHfgN0oP90"
CREDS_FILE  = "credentials.json"           # або os.getenv("GOOGLE_CREDS_PATH")
NOTIFY_CHAT = os.getenv("NOTIFY_CHAT_ID")  # ID чату куди Жора напише про успіх

# Назви місяців українською
MONTHS_UA = {
    1:  ("СІЧЕНЬ",   "грудень"),
    2:  ("ЛЮТИЙ",    "січень"),
    3:  ("БЕРЕЗЕНЬ", "лютий"),
    4:  ("КВІТЕНЬ",  "березень"),
    5:  ("ТРАВЕНЬ",  "квітень"),
    6:  ("ЧЕРВЕНЬ",  "травень"),
    7:  ("ЛИПЕНЬ",   "червень"),
    8:  ("СЕРПЕНЬ",  "липень"),
    9:  ("ВЕРЕСЕНЬ", "серпень"),
    10: ("ЖОВТЕНЬ",  "вересень"),
    11: ("ЛИСТОПАД", "жовтень"),
    12: ("ГРУДЕНЬ",  "листопад"),
}
# ─────────────────────────────────────────────────────────────


def get_sheet_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    return gspread.authorize(creds)


def get_month_dates(year: int, month: int) -> list[str]:
    days = calendar.monthrange(year, month)[1]
    return [f"{d:02d}.{month:02d}" for d in range(1, days + 1)]


def create_new_month_sheet() -> str:
    """
    Головна функція: дублює поточний лист, оновлює дати, чистить клієнтів.
    Повертає рядок зі статусом для відправки в Telegram.
    """
    now        = datetime.now()
    year       = now.year
    month      = now.month

    new_name_ua, prev_name_ua = MONTHS_UA[month]
    new_sheet_name = f"{new_name_ua}({prev_name_ua})"

    # Визначаємо попередній місяць (звідки копіюємо)
    prev_month = month - 1 if month > 1 else 12
    prev_year  = year if month > 1 else year - 1
    prev_name_full, prev_prev = MONTHS_UA[prev_month]
    source_sheet_name = f"{prev_name_full}({prev_prev})"

    gc = get_sheet_client()
    sh = gc.open_by_key(SHEET_ID)

    existing = [ws.title for ws in sh.worksheets()]

    # Якщо вже є — не дублюємо
    if new_sheet_name in existing:
        msg = f"⚠️ Лист *{new_sheet_name}* вже існує — пропускаю."
        logger.warning(msg)
        return msg

    # Знайти вихідний лист
    if source_sheet_name not in existing:
        msg = f"❌ Не знайшов лист *{source_sheet_name}* — не можу скопіювати."
        logger.error(msg)
        return msg

    source_ws = sh.worksheet(source_sheet_name)

    # 1. Дублюємо лист (зберігає форматування + формули)
    body = {
        "requests": [{
            "duplicateSheet": {
                "sourceSheetId": source_ws.id,
                "insertSheetIndex": len(sh.worksheets()),
                "newSheetName": new_sheet_name,
            }
        }]
    }
    sh.batch_update(body)
    logger.info(f"Лист '{new_sheet_name}' створено")

    new_ws = sh.worksheet(new_sheet_name)

    # 2. Нові дати
    new_dates     = get_month_dates(year, month)
    days_in_month = len(new_dates)

    date_cells = [
        gspread.Cell(i + 2, 1, d)
        for i, d in enumerate(new_dates)
    ]
    new_ws.update_cells(date_cells, value_input_option="USER_ENTERED")

    # 3. Очистити зайній рядок якщо місяць < 31 дня
    if days_in_month < 31:
        for extra in range(days_in_month + 2, 33):
            new_ws.batch_clear([f"A{extra}:D{extra}"])

    # 4. Очистити дані клієнтів (Клієнт, Контакт, Сума замовлення)
    new_ws.batch_clear([f"B2:D{days_in_month + 1}"])

    msg = (
        f"✅ *Жора:* Новий лист готовий!\n"
        f"📋 *{new_sheet_name}* — {days_in_month} днів\n"
        f"🗓 Дати: {new_dates[0]} — {new_dates[-1]}\n"
        f"🧹 Дані клієнтів очищено"
    )
    logger.info(msg)
    return msg


async def scheduled_job(bot):
    """Задача яку APScheduler запускає 1-го числа о 08:00"""
    logger.info("🕗 Запуск автосоздания листа...")
    try:
        result = create_new_month_sheet()
        if NOTIFY_CHAT:
            await bot.send_message(
                chat_id=NOTIFY_CHAT,
                text=result,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Помилка при створенні листа: {e}")
        if NOTIFY_CHAT:
            await bot.send_message(
                chat_id=NOTIFY_CHAT,
                text=f"❌ Помилка автосоздания листа:\n`{e}`",
                parse_mode="Markdown"
            )


def setup_scheduler(application):
    """
    Підключи цю функцію в основний файл бота:

        from month_sheet import setup_scheduler
        setup_scheduler(application)
    """
    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")

    scheduler.add_job(
        scheduled_job,
        trigger="cron",
        day=1,          # 1-ше число
        hour=8,         # 08:00
        minute=0,
        kwargs={"bot": application.bot},
    )

    scheduler.start()
    logger.info("✅ Планувальник запущено: новий лист — щомісяця 1-го о 08:00 (Київ)")
    return scheduler
