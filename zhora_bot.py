"""
ZHORA — Telegram-бот для клінінгової компанії.

Архітектура:
  - main()              entry point, asyncio.run
  - Config              env-vars + перевірка при старті
  - Database            asyncpg pool, історія + lead форми (з fallback на in-memory)
  - Sheets              синхронні виклики gspread в executor
  - AI                  Anthropic Claude (текст + vision)
  - Handlers            обробка повідомлень / callback queries
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import anthropic
import gspread
from google.oauth2.service_account import Credentials
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Шум від HTTP-бібліотек гасимо
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)

log = logging.getLogger("zhora")


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"❌ Не задана обов'язкова env-var: {name}")
    return value


def _parse_whitelist(raw: str) -> set[int]:
    ids = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            log.warning("WHITELIST_IDS: '%s' не схоже на user_id, пропустив", chunk)
    return ids


TELEGRAM_TOKEN = _required_env("SHOHA_TOKEN")
ANTHROPIC_KEY = _required_env("ANTHROPIC_KEY")
GOOGLE_CREDS_JSON = _required_env("GOOGLE_CREDS_JSON")
SHEET_ID = _required_env("GOOGLE_SHEET_ID")

WHITELIST: set[int] = _parse_whitelist(os.environ.get("WHITELIST_IDS", ""))
if not WHITELIST:
    log.warning("WHITELIST_IDS порожній — НІХТО не зможе користуватися ботом")

DATABASE_URL = os.environ.get("DATABASE_URL")  # опціональний

DIALOG_TIMEOUT = 300  # секунд активної бесіди
HISTORY_LIMIT = 10    # повідомлень на чат
ANTHROPIC_MODEL = "claude-sonnet-4-6"
ANTHROPIC_MAX_TOKENS = 800


# ─────────────────────────────────────────────────────────────────────────────
# Константи (промпт, місяці, забруднення)
# ─────────────────────────────────────────────────────────────────────────────

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


MONTH_NAMES = {
    1:  ["січень", "січня", "январь", "января", "january"],
    2:  ["лютий", "лютого", "февраль", "февраля", "february"],
    3:  ["березень", "березня", "март", "марта", "march"],
    4:  ["квітень", "квітня", "апрель", "апреля", "april"],
    5:  ["травень", "травня", "май", "мая", "may"],
    6:  ["червень", "червня", "июнь", "июня", "june"],
    7:  ["липень", "липня", "июль", "июля", "july"],
    8:  ["серпень", "серпня", "август", "августа", "august"],
    9:  ["вересень", "вересня", "сентябрь", "сентября", "september"],
    10: ["жовтень", "жовтня", "октябрь", "октября", "october"],
    11: ["листопад", "листопада", "ноябрь", "ноября", "november"],
    12: ["грудень", "грудня", "декабрь", "декабря", "december"],
}

CONTAMINATIONS: list[tuple[str, str]] = [
    ("🟡 Жир", "grease"), ("🔵 Вапняний наліт/камінь", "limestone"),
    ("🟤 Іржа", "rust"), ("⬛ Цвіль/пліснява", "mold"),
    ("🪟 Брудні вікна", "windows"), ("🍳 Плита/духовка/холодильник", "appliances"),
    ("🔲 Шви плитки", "tile_joints"), ("🧹 Складні плями", "stains"),
    ("👃 Неприємний запах", "smell"), ("🐾 Шерсть тварин", "pet_hair"),
    ("📏 Високі стелі", "high_ceiling"), ("🏗 Після ремонту", "after_repair"),
    ("💀 Запущений об'єкт", "neglected"), ("🛋 М'які меблі/килими", "soft_furniture"),
    ("💧 Немає води/світла", "no_utilities"), ("🌸 Потрібен парфум", "perfume"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Database (Postgres або in-memory fallback)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChatState:
    history: list[dict[str, str]] = field(default_factory=list)
    last_active: float = 0.0


class Storage:
    """
    Зберігає історію діалогів і стан форми ліда.
    Якщо DATABASE_URL заданий — Postgres, інакше — пам'ять процесу.
    """

    def __init__(self) -> None:
        self._memory: dict[int, ChatState] = {}
        self._lead_forms: dict[int, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._pg_ok = False

    async def setup(self) -> None:
        if not (HAS_POSTGRES and DATABASE_URL):
            log.info("Storage: in-memory (DATABASE_URL не заданий або psycopg2 відсутній)")
            return
        try:
            await asyncio.to_thread(self._init_pg_schema)
            self._pg_ok = True
            log.info("Storage: Postgres OK")
        except Exception as exc:
            log.exception("Storage: Postgres ініціалізація провалилась — fallback на пам'ять. %s", exc)

    def _connect(self):
        return psycopg2.connect(DATABASE_URL, connect_timeout=10)

    def _init_pg_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    chat_id BIGINT NOT NULL,
                    seq SERIAL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS chat_history_chat_idx ON chat_history(chat_id, seq);

                CREATE TABLE IF NOT EXISTS chat_meta (
                    chat_id BIGINT PRIMARY KEY,
                    last_active TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            conn.commit()

    # ── історія ────────────────────────────────────────────────────────
    async def get_history(self, chat_id: int) -> list[dict[str, str]]:
        if self._pg_ok:
            return await asyncio.to_thread(self._pg_get_history, chat_id)
        async with self._lock:
            return list(self._memory.setdefault(chat_id, ChatState()).history)

    def _pg_get_history(self, chat_id: int) -> list[dict[str, str]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM chat_history "
                "WHERE chat_id = %s ORDER BY seq DESC LIMIT %s",
                (chat_id, HISTORY_LIMIT),
            )
            rows = cur.fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    async def append_history(self, chat_id: int, role: str, content: str) -> None:
        if self._pg_ok:
            await asyncio.to_thread(self._pg_append_history, chat_id, role, content)
            return
        async with self._lock:
            state = self._memory.setdefault(chat_id, ChatState())
            state.history.append({"role": role, "content": content})
            state.history = state.history[-HISTORY_LIMIT:]
            state.last_active = time.time()

    def _pg_append_history(self, chat_id: int, role: str, content: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_history(chat_id, role, content) VALUES (%s, %s, %s)",
                (chat_id, role, content),
            )
            cur.execute(
                "INSERT INTO chat_meta(chat_id, last_active) VALUES (%s, now()) "
                "ON CONFLICT (chat_id) DO UPDATE SET last_active = now()",
                (chat_id,),
            )
            # Тримаємо тільки останні HISTORY_LIMIT повідомлень на чат
            cur.execute(
                "DELETE FROM chat_history WHERE chat_id = %s AND seq NOT IN ("
                "SELECT seq FROM chat_history WHERE chat_id = %s ORDER BY seq DESC LIMIT %s)",
                (chat_id, chat_id, HISTORY_LIMIT),
            )
            conn.commit()

    async def is_dialog_active(self, chat_id: int) -> bool:
        if self._pg_ok:
            return await asyncio.to_thread(self._pg_is_active, chat_id)
        async with self._lock:
            state = self._memory.get(chat_id)
            return bool(state) and (time.time() - state.last_active) < DIALOG_TIMEOUT

    def _pg_is_active(self, chat_id: int) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT EXTRACT(EPOCH FROM (now() - last_active)) FROM chat_meta WHERE chat_id = %s",
                (chat_id,),
            )
            row = cur.fetchone()
        return bool(row) and row[0] is not None and row[0] < DIALOG_TIMEOUT

    async def touch_dialog(self, chat_id: int) -> None:
        if self._pg_ok:
            await asyncio.to_thread(self._pg_touch, chat_id)
            return
        async with self._lock:
            self._memory.setdefault(chat_id, ChatState()).last_active = time.time()

    def _pg_touch(self, chat_id: int) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_meta(chat_id, last_active) VALUES (%s, now()) "
                "ON CONFLICT (chat_id) DO UPDATE SET last_active = now()",
                (chat_id,),
            )
            conn.commit()

    # ── lead форми (in-memory: губляться при рестарті, але це 30 секунд) ─
    def get_lead_form(self, user_id: int) -> dict[str, Any] | None:
        return self._lead_forms.get(user_id)

    def set_lead_form(self, user_id: int, data: dict[str, Any]) -> None:
        self._lead_forms[user_id] = data

    def pop_lead_form(self, user_id: int) -> dict[str, Any] | None:
        return self._lead_forms.pop(user_id, None)


storage = Storage()


# ─────────────────────────────────────────────────────────────────────────────
# Google Sheets (синхронні виклики через executor)
# ─────────────────────────────────────────────────────────────────────────────

def _gc():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def _get_ws_sync(month: int | None = None):
    gc = _gc()
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


def _write_lead_sync(name: str, phone: str, amount: str | None,
                     target_date: str | None, month: int | None) -> tuple[bool, str]:
    ws = _get_ws_sync(month)
    target = target_date if target_date else datetime.now().strftime("%d.%m")

    col_a = ws.col_values(1)
    row_num = None
    for i, val in enumerate(col_a):
        if str(val).strip() == target:
            row_num = i + 1
            break

    # Якщо дати в таблиці немає — додаємо новий рядок з нею
    if not row_num:
        ws.append_row([target, name, phone, amount or ""])
        return True, target

    ws.update_cell(row_num, 2, name)
    ws.update_cell(row_num, 3, phone)
    if amount:
        clean_amount = re.sub(r"[^\d.]", "", amount.replace(",", "."))
        if clean_amount:
            ws.update_cell(row_num, 4, clean_amount)
    return True, target


def _stats_sync() -> dict[str, int]:
    ws = _get_ws_sync()
    all_vals = ws.get_all_values()
    total, total_sum = 0, 0.0
    for row in all_vals[1:]:
        if len(row) > 1 and str(row[1]).strip():
            total += 1
            if len(row) > 3:
                num = re.sub(r"[^\d.]", "", str(row[3]).replace(",", "."))
                try:
                    total_sum += float(num)
                except ValueError:
                    pass
    return {
        "total": total,
        "sum": int(total_sum),
        "avg": int(total_sum // total) if total else 0,
    }


def _search_sync(query: str) -> list[dict[str, str]]:
    gc = _gc()
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
                    "amount": amount,
                })
    return results


# Async обгортки
async def write_lead(name: str, phone: str, amount: str | None,
                     target_date: str | None, month: int | None) -> tuple[bool, str]:
    try:
        return await asyncio.to_thread(_write_lead_sync, name, phone, amount, target_date, month)
    except Exception as exc:
        log.exception("Sheets write_lead error: %s", exc)
        return False, f"Помилка таблиці: {exc}"


async def get_stats() -> dict[str, int]:
    try:
        return await asyncio.to_thread(_stats_sync)
    except Exception as exc:
        log.exception("Sheets stats error: %s", exc)
        return {}


async def search_client(query: str) -> list[dict[str, str]]:
    try:
        return await asyncio.to_thread(_search_sync, query)
    except Exception as exc:
        log.exception("Sheets search error: %s", exc)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# AI (Anthropic Claude)
# ─────────────────────────────────────────────────────────────────────────────

ai_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


def _claude_text_sync(history: list[dict[str, str]]) -> str:
    response = ai_client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=ANTHROPIC_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=history,
    )
    return response.content[0].text


def _claude_vision_sync(image_b64: str, prompt: str) -> str:
    response = ai_client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=ANTHROPIC_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return response.content[0].text


async def claude_text(history: list[dict[str, str]]) -> str:
    return await asyncio.to_thread(_claude_text_sync, history)


async def claude_vision(image_b64: str, prompt: str) -> str:
    return await asyncio.to_thread(_claude_vision_sync, image_b64, prompt)


def normalize_history(history: list[dict[str, str]], new_user_msg: str) -> list[dict[str, str]]:
    """
    Anthropic API вимагає чергування ролей user/assistant.
    Якщо в історії останнє повідомлення user — склеюємо його з новим.
    Також гарантуємо що історія починається з user.
    """
    out: list[dict[str, str]] = []
    for msg in history:
        if out and out[-1]["role"] == msg["role"]:
            # Склеюємо однакові ролі підряд
            out[-1] = {"role": msg["role"], "content": out[-1]["content"] + "\n" + msg["content"]}
        else:
            out.append({"role": msg["role"], "content": msg["content"]})

    # Видаляємо assistant з початку (історія має починатись з user)
    while out and out[0]["role"] != "user":
        out.pop(0)

    # Додаємо нове user-повідомлення
    if out and out[-1]["role"] == "user":
        out[-1] = {"role": "user", "content": out[-1]["content"] + "\n" + new_user_msg}
    else:
        out.append({"role": "user", "content": new_user_msg})

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Парсинг дат
# ─────────────────────────────────────────────────────────────────────────────

WEEKDAYS = {
    0: ["понеділок", "пн", "понедельник"],
    1: ["вівторок", "вт", "вторник"],
    2: ["середа", "ср", "среда"],
    3: ["четвер", "чт", "четверг"],
    4: ["п'ятниця", "пятниця", "пт", "пятница"],
    5: ["субота", "сб", "суббота"],
    6: ["неділя", "нд", "вс", "воскресенье"],
}


def parse_date(text: str) -> tuple[str | None, int]:
    """
    Парсить дату з тексту. Повертає (DD.MM або None, місяць 1-12).
    Розуміє: "сьогодні", "завтра", "5 мая", "10го липня", "30.05",
    "наступного понеділка", "цієї пятниці" тощо.
    """
    t = text.lower()
    now = datetime.now()

    # 1) сьогодні / завтра / післязавтра
    if re.search(r"\bсьогодні|сегодня|today\b", t):
        return now.strftime("%d.%m"), now.month
    if re.search(r"\bзавтра|tomorrow|зафтра\b", t):
        d = now + timedelta(days=1)
        return d.strftime("%d.%m"), d.month
    if re.search(r"\bпіслязавтра|послезавтра\b", t):
        d = now + timedelta(days=2)
        return d.strftime("%d.%m"), d.month

    # 2) DD.MM або DD/MM
    m = re.search(r"(\d{1,2})[./](\d{1,2})", t)
    if m:
        day, mon = int(m.group(1)), int(m.group(2))
        if 1 <= day <= 31 and 1 <= mon <= 12:
            return f"{day:02d}.{mon:02d}", mon

    # 3) "5 мая", "10 липня", "5го мая", "10го липня"
    for mon_num, names in MONTH_NAMES.items():
        for name in names:
            pattern = r"\b(\d{1,2})\s*(?:го|ого|е|е\s+числа)?\s+" + re.escape(name) + r"\b"
            m = re.search(pattern, t)
            if m:
                day = int(m.group(1))
                if 1 <= day <= 31:
                    return f"{day:02d}.{mon_num:02d}", mon_num

    # 4) "наступного понеділка", "цієї пятниці", "у вівторок"
    for wd_num, wd_names in WEEKDAYS.items():
        for name in wd_names:
            pattern = r"(?:наступн\w*|цієї|на)\s+" + re.escape(name)
            if re.search(pattern, t):
                # Знайти найближчий цей weekday у майбутньому (>=1 день)
                days_ahead = (wd_num - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                d = now + timedelta(days=days_ahead)
                return d.strftime("%d.%m"), d.month

    return None, now.month


# ─────────────────────────────────────────────────────────────────────────────
# Telegram handlers
# ─────────────────────────────────────────────────────────────────────────────

def checklist_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    keyboard = []
    for label, key in CONTAMINATIONS:
        mark = "✅ " if key in selected else ""
        keyboard.append([InlineKeyboardButton(mark + label, callback_data=f"check_{key}")])
    keyboard.append([InlineKeyboardButton("Готово — отримати звіт", callback_data="check_done")])
    return InlineKeyboardMarkup(keyboard)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if user_id not in WHITELIST:
        log.info("rejected user_id=%s (not in whitelist)", user_id)
        return

    chat_id = update.effective_chat.id
    text = update.message.text or ""
    caption = update.message.caption or ""
    has_photo = bool(update.message.photo)
    text_lower = text.lower()
    caption_lower = caption.lower()

    trigger = "жора" in text_lower or "жора" in caption_lower
    is_active = await storage.is_dialog_active(chat_id)

    if trigger or is_active:
        await storage.touch_dialog(chat_id)

    # ── Команда скасування діалогу/форми ────────────────────────────────
    if trigger and re.search(r"\b(скасуй|відміна|отмена|cancel|выход|вихід)\b", text_lower):
        storage.pop_lead_form(user_id)
        await update.message.reply_text("Ок, скасував.")
        return

    # ── Форма ліда (крок за кроком) ────────────────────────────────────
    form = storage.get_lead_form(user_id)
    if form:
        await _handle_lead_form_step(update, form, text)
        return

    if not trigger and not is_active and not has_photo:
        return

    # ── Швидкий запис ліда ─────────────────────────────────────────────
    if trigger and re.search(r"запиши\s+л[іиi]да?|записать\s+лид|запиши\s+лида", text_lower):
        await _handle_quick_lead(update, text)
        return

    # ── Інтерактивна форма ліда ────────────────────────────────────────
    if trigger and re.search(r"нов(ий|ого)?\s+л[іиi]д|новый\s+лид|додай\s+л[іиi]да?|добавь\s+лид|форма", text_lower):
        target_date, month = parse_date(text_lower)
        storage.set_lead_form(user_id, {"step": "name", "date": target_date, "month": month})
        date_label = target_date or datetime.now().strftime("%d.%m")
        await update.message.reply_text(f"📋 Новий лід на {date_label}\n\nІм'я клієнта:")
        return

    # ── Пошук ──────────────────────────────────────────────────────────
    if trigger and re.search(r"\b(знайди|шукай|найди|поищи)\b", text_lower):
        await _handle_search(update, text_lower)
        return

    # ── Статистика ─────────────────────────────────────────────────────
    if trigger and re.search(r"\b(стат|скільки|сколько|підсумок|итог|доход)\b", text_lower):
        await _handle_stats(update)
        return

    # ── Чеклист ────────────────────────────────────────────────────────
    if trigger and re.search(
        r"\b(огляд|об'єкт|объект|осмотр|що брати|що взяти|збери|"
        r"дай кнопки|покажи кнопки|на уборку|на прибирання|що нести|"
        r"їдемо на|виїзд|выезд|что брать|что взять|собери)\b",
        text_lower,
    ):
        context.user_data["checklist"] = []
        await update.message.reply_text(
            "Огляд об'єкту — відмічай що є:",
            reply_markup=checklist_keyboard([]),
        )
        return

    # ── Фото ───────────────────────────────────────────────────────────
    if has_photo:
        await _handle_photo(update, context, chat_id, caption)
        return

    # ── Звичайний діалог ──────────────────────────────────────────────
    if trigger or is_active:
        await _handle_dialog(update, chat_id, text)


async def _handle_lead_form_step(update: Update, form: dict[str, Any], text: str) -> None:
    user_id = update.effective_user.id
    text_lower = text.lower()
    step = form["step"]

    if step == "name":
        form["name"] = text.strip()
        form["step"] = "phone"
        storage.set_lead_form(user_id, form)
        await update.message.reply_text("📞 Телефон:")
        return

    if step == "phone":
        form["phone"] = text.strip()
        form["step"] = "amount"
        storage.set_lead_form(user_id, form)
        await update.message.reply_text("💰 Сума замовлення:")
        return

    if step == "amount":
        form["amount"] = text.strip()
        form["step"] = "confirm"
        storage.set_lead_form(user_id, form)
        date_label = form.get("date") or datetime.now().strftime("%d.%m")
        await update.message.reply_text(
            f"Записую на {date_label}:\n"
            f"👤 {form['name']}\n"
            f"📞 {form['phone']}\n"
            f"💰 {form['amount']}\n\nВсе вірно? (так/ні)"
        )
        return

    if step == "confirm":
        if any(w in text_lower for w in ["так", "да", "ок", "ok", "yes", "вірно", "верно"]):
            data = storage.pop_lead_form(user_id)
            if not data:
                return
            ok, result = await write_lead(
                data["name"], data["phone"],
                data.get("amount"), data.get("date"), data.get("month"),
            )
            if ok:
                await update.message.reply_text(f"✅ Записано на {result}!")
            else:
                await update.message.reply_text(f"❌ {result}")
        else:
            storage.pop_lead_form(user_id)
            await update.message.reply_text("Скасовано.")


async def _handle_quick_lead(update: Update, text: str) -> None:
    text_lower = text.lower()
    target_date, month = parse_date(text_lower)
    cleaned = re.sub(r"жора[,\s]*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"запиши\s+л[іиi]да?\s*(на\s+\S+(\s+\S+)?)?\s*[:—\-]?\s*",
        "", cleaned, flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"записать\s+лид[а]?\s*(на\s+\S+(\s+\S+)?)?\s*[:—\-]?\s*",
        "", cleaned, flags=re.IGNORECASE,
    )
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]

    if len(parts) < 2:
        await update.message.reply_text(
            "Формат:\n"
            "_Жора, запиши ліда: Іван, 0660123456, 2700_\n"
            "_Жора, запиши ліда на завтра: Іван, 0660123456, 2700_\n"
            "_Жора, запиши ліда на 30.05: Іван, 0660123456, 2700_\n"
            "_Жора, запиши ліда на 5 травня: Іван, 0660123456, 2700_",
            parse_mode="Markdown",
        )
        return

    name = parts[0]
    phone = parts[1]
    amount = parts[2] if len(parts) >= 3 else None
    ok, result = await write_lead(name, phone, amount, target_date, month)
    if ok:
        msg = f"✅ Записано!\n\n📅 {result}\n👤 {name}\n📞 {phone}"
        if amount:
            clean_a = re.sub(r"[^\d.]", "", amount)
            if clean_a:
                msg += f"\n💰 {clean_a} грн"
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text(f"❌ {result}")


async def _handle_search(update: Update, text_lower: str) -> None:
    query = re.sub(r"жора[,\s]*", "", text_lower)
    query = re.sub(r"\b(знайди|шукай|найди|поищи)\b[,\s]*", "", query).strip()
    if not query:
        await update.message.reply_text("Що шукати? Напиши ім'я або телефон.")
        return

    results = await search_client(query)
    if not results:
        await update.message.reply_text(f"Нічого не знайшов по «{query}» 🤷")
        return

    total = len(results)
    shown = results[-10:]
    header = f"🔍 Знайдено: {total}"
    if total > 10:
        header += f" (показую останніх 10)"
    lines = [header + "\n" + "─" * 20]
    for r in shown:
        lines.append(
            f"📅 {r['date']} ({r['sheet']})\n"
            f"👤 {r['name']}\n"
            f"📞 {r['phone']}\n"
            f"💰 {r['amount']}\n"
            + "─" * 20
        )
    await update.message.reply_text("\n".join(lines))


async def _handle_stats(update: Update) -> None:
    stats = await get_stats()
    if not stats:
        await update.message.reply_text("Таблиця порожня або помилка підключення.")
        return
    await update.message.reply_text(
        "📊 *Статистика*\n\n"
        f"📋 Всього клієнтів: {stats['total']}\n"
        f"💰 Загальна сума: {stats['sum']} грн\n"
        f"📈 Середній чек: {stats['avg']} грн",
        parse_mode="Markdown",
    )


async def _handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        chat_id: int, caption: str) -> None:
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    image_b64 = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")

    base_prompt = (
        "Проаналізуй це фото з точки зору клінінгу. "
        "Що тут забруднено? Які засоби і інвентар потрібні? "
        "Використовуй тільки хімію Clinex та Karpax."
    )
    prompt = f"{base_prompt}\n\nКоментар бригадира: {caption}" if caption else base_prompt

    await storage.touch_dialog(chat_id)
    try:
        reply = await claude_vision(image_b64, prompt)
        await storage.append_history(chat_id, "user", f"[фото] {caption or '(без коментаря)'}")
        await storage.append_history(chat_id, "assistant", reply)
        await update.message.reply_text(reply)
    except Exception as exc:
        log.exception("Vision error: %s", exc)
        await update.message.reply_text(f"Помилка аналізу фото: {exc}")


async def _handle_dialog(update: Update, chat_id: int, text: str) -> None:
    clean_text = re.sub(r"жора[,\s]*", "", text, flags=re.IGNORECASE).strip()
    if not clean_text:
        return

    history = await storage.get_history(chat_id)
    messages = normalize_history(history, clean_text)

    try:
        reply = await claude_text(messages)
        await storage.append_history(chat_id, "user", clean_text)
        await storage.append_history(chat_id, "assistant", reply)
        await update.message.reply_text(reply)
    except Exception as exc:
        log.exception("Claude text error: %s", exc)
        await update.message.reply_text(f"Помилка: {exc}")


async def handle_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in WHITELIST:
        return

    selected: list[str] = context.user_data.setdefault("checklist", [])

    if query.data == "check_done":
        if not selected:
            await query.edit_message_text("Нічого не відмічено. Об'єкт чистий?")
            return
        labels = {key: label for label, key in CONTAMINATIONS}
        selected_labels = [labels[k] for k in selected if k in labels]
        report_header = "ЗВІТ ОГЛЯДУ\n\nЗнайдено:\n" + "\n".join(f"- {l}" for l in selected_labels)
        prompt = (
            f"Бригадир відмітив забруднення: {', '.join(selected_labels)}. "
            "Склади список що взяти з нашої хімії Clinex та Karpax, інвентар, і короткі поради."
        )
        try:
            reply = await claude_text([{"role": "user", "content": prompt}])
            await query.edit_message_text(report_header + "\n\n" + reply)
        except Exception as exc:
            log.exception("Checklist AI error: %s", exc)
            await query.edit_message_text(f"Помилка: {exc}")
        context.user_data["checklist"] = []
        return

    key = query.data.replace("check_", "")
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    context.user_data["checklist"] = selected
    await query.edit_message_reply_markup(reply_markup=checklist_keyboard(selected))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled error: %s", context.error)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    log.info("Starting ZHORA bot. Whitelist size=%d, Postgres=%s",
             len(WHITELIST), "yes" if (HAS_POSTGRES and DATABASE_URL) else "no")

    await storage.setup()

    app: Application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CallbackQueryHandler(handle_checklist, pattern="^check_"))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_error_handler(on_error)

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("Bot is up and polling.")

    # Тримаємо процес живим
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        log.info("Shutting down...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
