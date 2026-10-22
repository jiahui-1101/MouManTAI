"""Deterministic L0 extraction rules over StoredMessage.

Extracts explicit order references, known SKUs, quantities, normalized units,
and timezone-aware delivery dates/deadlines. All observations preserve exact
Unicode code-point evidence spans [start, end) against the original text.
Unresolved, invalid, or conflicting terms remain proposed and require manual review.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import re
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .extraction import ExtractionResult
from .ingestion_schemas import StoredMessage
from .schemas import ExtractedField, FieldEvidence
from .request_intent import request_intent

VERSION = "p1-deterministic-v6"

# ---------------------------------------------------------------------------
# Catalogs and Normalization Maps
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProductAlias:
    tenant_id: str
    sku: str
    aliases: tuple[str, ...]
    unit: str


PROVISIONAL_PRODUCTS = tuple(
    ProductAlias(tenant, "BURGER", ("burger", "burgers", "beef burger", "beef burgers", "chicken burger", "chicken burgers", "汉堡", "汉堡包", "roti burger", "bgr", "bgrs", "hbg", "buhger", "漢堡", "漢堡包"), "pcs")
    for tenant in ("synthetic_tenant_a", "synthetic_tenant_b")
)

UNIT_NORMALIZATION: dict[str, str] = {
    # pieces family (EN, ZH, MS)
    "pc": "pcs",
    "pcs": "pcs",
    "piece": "pcs",
    "pieces": "pcs",
    "个": "pcs",
    "個": "pcs",
    "件": "pcs",
    "biji": "pcs",
    "buah": "pcs",
    "bj": "pcs",
    "bjk": "pcs",
    "bungkus": "pack",
    "paket": "pack",
    "buns": "pcs",
    "bun": "pcs",
    # box family (EN, ZH, MS)
    "box": "box",
    "boxes": "box",
    "盒": "box",
    "箱": "box",
    "kotak": "box",
    "bx": "box",
    "bxs": "box",
    "koli": "box",
    # kg family
    "kg": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "公斤": "kg",
    # Literal packaging names only; these aliases never convert quantities.
    "pack": "pack", "packs": "pack", "包": "pack", "袋": "bag",
    "bag": "bag", "bags": "bag",
    "cup": "cup", "cups": "cup", "杯": "cup", "cawan": "cup",
    "bottle": "bottle", "bottles": "bottle", "瓶": "bottle", "botol": "bottle",
    "carton": "carton", "cartons": "carton", "karton": "carton",
    "tray": "tray", "trays": "tray", "盘": "tray", "盤": "tray",
    "set": "set", "sets": "set", "份": "set",
    "pax": "pax", "portion": "portion", "portions": "portion",
    "bowl": "bowl", "bowls": "bowl", "碗": "bowl", "mangkok": "bowl",
    "can": "can", "cans": "can", "罐": "can", "tin": "can", "tins": "can",
    "plate": "plate", "plates": "plate", "碟": "plate", "pinggan": "plate",
    "tub": "tub", "tubs": "tub", "桶": "tub", "tong": "tub",
}

# ---------------------------------------------------------------------------
# Regular Expressions
# ---------------------------------------------------------------------------

ORDER_RE = re.compile(r"(?<![A-Za-z0-9_])(?:ORD-[0-9]+|PO-[0-9A-Z\-]+|INV-[0-9A-Z\-]+|synthetic_order_[a-z0-9]+)(?![A-Za-z0-9_])", re.IGNORECASE)
CONFIRMATION_CONSTRAINT_RE = re.compile(
    r'\b(?:(?:manual\s+)?written\s+confirmation\s+(?:is\s+)?required|manual\s+written\s+confirmation|written\s+confirmation\s+required|'
    r'manual\s+confirmation\s+(?:is\s+)?required|manual\s+confirmation\s+required|'
    r'perlu\s+pengesahan\s+bertulis|pengesahan\s+bertulis\s+diperlukan|pengesahan\s+manual\s+diperlukan|'
    r'需要书面确认|需书面确认|须人工书面确认|需要人工确认|'
    r'subject\s+to\s+(?:written\s+)?confirmation|tertakluk\s+kepada\s+pengesahan)\b',
    re.IGNORECASE
)
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.,+\-])[+\-]?[0-9]+(?:[.,][0-9]+)?(?![A-Za-z0-9_.,])")

# Quantity + optional unit prefix before product mention (supports optional 'of' / 'daripada')
QUANTITY_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9_.,+\-])(?P<quantity>[+\-]?[0-9]+(?:[.,][0-9]+)?)"
    r"(?:\s*(?P<unit>[A-Za-z]+|[\u4e00-\u9fff]))?"
    r"(?:\s+(?:of|daripada)\s*(?:the\s*)?)?\s*$",
    re.IGNORECASE
)

# Packaging containing clause preceding product mention (e.g., '4 boxes containing 20 burgers')
CONTAINING_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9_.,+\-])(?P<quantity>[0-9]+)\s+"
    r"(?P<unit>boxes|box|packs|pack|cartons|carton|bags|bag|trays|tray|kotak|bungkus)\s+"
    r"containing\s+(?P<per_box>[0-9]+)\s*$",
    re.IGNORECASE
)

UNSAFE_ASSOCIATION_RE = re.compile(
    r"\b(?:and|or|dan|atau|not|no|cancel|instead|sorry|correction|jangan|batal)\b|和|或|不要|改成|取消",
    re.IGNORECASE
)

# Ambiguous / unsupported relative expressions that must be marked UNRESOLVED
AMBIGUOUS_DELIVERY_RE = re.compile(
    r"\b(?:next\s+(?:friday|monday|tuesday|wednesday|thursday|saturday|sunday|week|month)|"
    r"this\s+weekend|sometime\s+(?:next\s+week|soon)|in\s+a\s+few\s+days|"
    r"asap|as\s+soon\s+as\s+possible|soon|same\s+as\s+last\s+time|bila-bila|anytime)\b|"
    r"(?:下周[一二三四五六日七]?|下个星期[一二三四五六天]?|下个月|这周末|尽快|马上|越快越好|老样子|照旧|再定|待定|哪天都可以|随时)",
    re.IGNORECASE
)

# Relative dates (EN, ZH, MS)
REL_DATE_EN_RE = re.compile(r"\b(?P<rel>today|tomorrow|tmr|tmrw|2moro|day\s+after\s+tomorrow)\b", re.IGNORECASE)
REL_DAYS_EN_RE = re.compile(r"\b(?:in\s+)?(?P<days>\d+)\s+days?\s*(?:later|from\s+now)?\b", re.IGNORECASE)
REL_DATE_ZH_RE = re.compile(r"(?P<rel>今天|明天|大后天|后天)")
REL_DAYS_ZH_RE = re.compile(r"(?<!\d)(?P<days>\d+)\s*天[之以]?后")
REL_DATE_MS_RE = re.compile(r"\b(?P<rel>hari\s+ini|esok|besok|lusa|tulat|tulats)\b", re.IGNORECASE)
REL_DAYS_MS_RE = re.compile(r"\b(?:dalam\s+(?P<days1>\d+)\s+hari|(?P<days2>\d+)\s+hari\s+lagi)\b", re.IGNORECASE)

# ISO Date: YYYY-MM-DD
ISO_DATE_RE = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b")

# English Formatted Date: 24 October 2026, 24th Oct 2026, Oct 24, 2026
MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    # Malay month names
    "januari": 1, "februari": 2, "mac": 3, "mei": 5, "julai": 7, "ogos": 8, "oktober": 10, "disember": 12,
}
MONTH_PATTERN = "|".join(MONTH_NAMES.keys())

DATE_DMY_RE = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<month>{MONTH_PATTERN})\s+(?P<year>\d{{4}})\b",
    re.IGNORECASE
)
DATE_MDY_RE = re.compile(
    rf"\b(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,)?\s+(?P<year>\d{{4}})\b",
    re.IGNORECASE
)

# Chinese Date: 2026年10月24日 / 10月24日
DATE_ZH_FULL_RE = re.compile(r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})[日号]")
DATE_ZH_SHORT_RE = re.compile(r"(?<!\d)(?P<month>\d{1,2})月(?P<day>\d{1,2})[日号]")
YEARLESS_DMY_RE = re.compile(rf"\b[0-9]{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{MONTH_PATTERN})\b", re.IGNORECASE)
YEARLESS_MDY_RE = re.compile(rf"\b(?:{MONTH_PATTERN})\s+[0-9]{{1,2}}(?:st|nd|rd|th)?\b", re.IGNORECASE)
NUMERIC_DATE_RE = re.compile(r"(?<![A-Za-z0-9])[0-9]{1,2}[/-][0-9]{1,2}(?:[/-][0-9]{2,4})?(?![A-Za-z0-9])")

WEEKDAY_MAP: dict[str, int] = {
    "monday": 0, "isnin": 0, "周一": 0, "星期一": 0, "礼拜一": 0,
    "tuesday": 1, "selasa": 1, "周二": 1, "星期二": 1, "礼拜二": 1,
    "wednesday": 2, "rabu": 2, "周三": 2, "星期三": 2, "礼拜三": 2,
    "thursday": 3, "khamis": 3, "周四": 3, "星期四": 3, "礼拜四": 3,
    "friday": 4, "jumaat": 4, "周五": 4, "星期五": 4, "礼拜五": 4,
    "saturday": 5, "sabtu": 5, "周六": 5, "星期六": 5, "礼拜六": 5,
    "sunday": 6, "ahad": 6, "周日": 6, "周天": 6, "星期天": 6, "星期日": 6, "礼拜天": 6, "礼拜日": 6,
}

WEEKDAY_RE = re.compile(
    r"\b(?:(?P<prefix_en>next|this)\s+)?(?P<name_en>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
    r"\b(?:hari\s+)?(?P<name_ms>isnin|selasa|rabu|khamis|jumaat|sabtu|ahad)(?:\s+(?P<suffix_ms>ni|depan))?\b|"
    r"(?P<prefix_zh>下周|下星期|这周|这星期)?(?P<name_zh>周[一二三四五六日天]|星期[一二三四五六天日]|礼拜[一二三四五六天日])",
    re.IGNORECASE
)

# Time patterns
TIME_12H_RE = re.compile(
    r"(?<![A-Za-z0-9_:])(?P<hour>[0-9]+)(?:[:.](?P<minute>[0-9]+))?"
    r"(?P<extra>(?::[0-9]+)*)\s*(?P<meridiem>am|pm|pg|ptg|pagi|petang|malam|tengah\s+hari)(?P<suffix>[A-Za-z0-9_]*)(?![A-Za-z0-9_:])",
    re.IGNORECASE
)
TIME_NOON_RE = re.compile(
    r"\b(?:(?P<hour>12)?\s*(?P<meridiem>noon|12nn))\b",
    re.IGNORECASE
)
TIME_24H_RE = re.compile(
    r"(?<![A-Za-z0-9_:])(?P<hour>[0-9]+):(?P<minute>[0-9]+)"
    r"(?P<extra>(?::[0-9]+)*)(?P<suffix>[A-Za-z_]*)(?![A-Za-z0-9_:])"
)
TIME_ZH_RE = re.compile(
    r"(?<![0-9])(?:(?P<meridiem>下午|晚上|上午|早上|中午|傍晚)\s*)?"
    r"(?P<hour>[0-9]+|[一二两三四五六七八九十]+)\s*(?:点|时)(?:(?P<minute>[0-9]+)分?|(?P<half>半))?(?P<extra>[0-9]+秒)?"
)
TIME_MS_RE = re.compile(
    r"\b(?:pukul|jam)\s+(?P<hour>[0-9]+)(?:[:.](?P<minute>[0-9]+))?"
    r"(?:\s*(?P<meridiem>pagi|tengah\s+hari|petang|malam))?\b",
    re.IGNORECASE
)
TIME_MS_PREFIX_RE = re.compile(
    r'\b(?P<meridiem>pagi|petang|malam|tengah\s+hari)\s+(?:pukul|jam)\s+'
    r'(?P<hour>[0-9]+)(?:[:.](?P<minute>[0-9]+))?\b', re.I)

# These semantics cannot be represented by EXACT/DEADLINE/DATE_ONLY. Keep
# the original expression unresolved rather than silently dropping a modifier.
UNSUPPORTED_TIME_SEMANTICS_RE = re.compile(
    r"\b(?:after|not\s+before|earlier\s+than|around|about|between|from|maybe|possibly|at\s+least|not\s+at|"
    r"not\s+by|mungkin|belum\s+pasti|tengok\s+dulu|selepas|UTC|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT|BST|CET|CEST|HKT|SGT|MYT|JST|AEST|AEDT)\b|"
    r"(?<![A-Za-z0-9])[+-][0-9]{2}:?[0-9]{2}(?![0-9])|"
    r"\b[A-Za-z_]+/[A-Za-z_]+\b|之后|以后|过后|大约|左右|不早于|不要|不是|再定|待定|(?<=点)后",
    re.IGNORECASE,
)

# Deadline indicators (EN, ZH, MS)
DEADLINE_PRE_RE = re.compile(
    r"\b(?:before|by|no\s+later\s+than|prior\s+to|until|"
    r"sebelum|selewat-lewatnya|paling\s+lambat|tak\s+lewat\s+dari)\b|"
    r"(?:最晚|不迟于)",
    re.IGNORECASE
)
DEADLINE_POST_RE = re.compile(r"^(?:之前|前)")
EXACT_INDICATOR_RE = re.compile(
    r"\b(?:at|on|for|precisely|pada|tepat\s+pada)\b|在|于",
    re.IGNORECASE
)

DELIVERY_CONFLICT_CONNECTOR_RE = re.compile(
    r"\b(?:or|and|或者|和)\b|[/或]",
    re.IGNORECASE
)

APPROXIMATE_MODIFIER_RE = re.compile(
    r"\b(?:around|about|approx(?:imately)?|roughly|kira-kira|agak-agak|anggaran)\b|大约|左右|大概",
    re.IGNORECASE
)
MEAL_PERIOD_RE = re.compile(
    r"\b(?:lunch\s*time|lunchtime|dinner\s*time|dinnertime|breakfast\s*time|breakfast|lunch|dinner|tengah\s*hari)\b|午饭时间|午餐时间|晚饭时间|晚餐时间|午餐|晚餐|早午餐",
    re.IGNORECASE
)
UNDECIDED_TIME_RE = re.compile(
    r"\b(?:not\s+sure\s+what\s+time|tengok\s+dulu|belum\s+pasti|tak\s+pasti)\b|待定|再定",
    re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Date/Time Parsing Logic
# ---------------------------------------------------------------------------

@dataclass
class ParsedDate:
    date_val: date
    start: int
    end: int
    raw: str


@dataclass
class ParsedTime:
    hour: int
    minute: int
    start: int
    end: int
    raw: str


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _unique_local_instant(wall: datetime, tz: ZoneInfo) -> tuple[datetime | None, str | None]:
    """ZoneInfo attachment alone accepts DST gaps/folds. Require a round trip
    for each fold choice and exactly one distinct UTC instant. Do not choose
    an offset or shift a nonexistent wall time without source evidence.
    """
    candidates = {}
    for fold in (0, 1):
        local = wall.replace(tzinfo=tz, fold=fold)
        instant = local.astimezone(timezone.utc)
        if instant.astimezone(tz).replace(tzinfo=None) == wall:
            candidates[instant] = local
    if not candidates:
        return None, "Nonexistent DST local time; explicit valid time required"
    if len(candidates) != 1:
        return None, "Ambiguous DST local time; explicit offset/disambiguation required"
    return next(iter(candidates.values())), None


def _find_all_dates(text: str, local_date: date | None) -> tuple[list[ParsedDate], list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]]]:
    """Find full dates; never assign a year to yearless/ambiguous formats.

    Returns valid dates, invalid calendars, missing-relative-context spans,
    and unresolved yearless/numeric date spans. Nested short matches do not
    count as a second date inside a complete (even invalid) date token.
    """
    valid: list[ParsedDate] = []
    invalid_calendar: list[tuple[int, int]] = []
    tz_required: list[tuple[int, int]] = []
    yearless: list[tuple[int, int]] = []

    # 1. Relative dates
    for m in REL_DATE_EN_RE.finditer(text):
        if local_date is None:
            tz_required.append((m.start(), m.end()))
        else:
            rel = m.group("rel").lower()
            if rel in ("tomorrow", "tmr", "tmrw", "2moro"):
                d = local_date + timedelta(days=1)
            elif rel == "day after tomorrow":
                d = local_date + timedelta(days=2)
            else:
                d = local_date
            valid.append(ParsedDate(d, m.start(), m.end(), m.group()))

    for m in REL_DATE_ZH_RE.finditer(text):
        if local_date is None:
            tz_required.append((m.start(), m.end()))
        else:
            rel = m.group("rel")
            delta = 3 if rel == "大后天" else 2 if rel == "后天" else 1 if rel == "明天" else 0
            valid.append(ParsedDate(local_date + timedelta(days=delta), m.start(), m.end(), m.group()))

    for m in REL_DATE_MS_RE.finditer(text):
        if local_date is None:
            tz_required.append((m.start(), m.end()))
        else:
            rel = m.group("rel").lower()
            delta = 3 if rel in ("tulat", "tulats") else 2 if rel == "lusa" else 1 if rel in ("esok", "besok") else 0
            valid.append(ParsedDate(local_date + timedelta(days=delta), m.start(), m.end(), m.group()))

    for m in REL_DAYS_EN_RE.finditer(text):
        if local_date is None:
            tz_required.append((m.start(), m.end()))
        else:
            days = int(m.group("days"))
            valid.append(ParsedDate(local_date + timedelta(days=days), m.start(), m.end(), m.group()))

    for m in REL_DAYS_ZH_RE.finditer(text):
        if local_date is None:
            tz_required.append((m.start(), m.end()))
        else:
            days = int(m.group("days"))
            valid.append(ParsedDate(local_date + timedelta(days=days), m.start(), m.end(), m.group()))

    for m in REL_DAYS_MS_RE.finditer(text):
        if local_date is None:
            tz_required.append((m.start(), m.end()))
        else:
            days = int(m.group("days1") or m.group("days2"))
            valid.append(ParsedDate(local_date + timedelta(days=days), m.start(), m.end(), m.group()))

    # 2. ISO Date
    for m in ISO_DATE_RE.finditer(text):
        d = _safe_date(int(m.group("year")), int(m.group("month")), int(m.group("day")))
        if d is None:
            invalid_calendar.append((m.start(), m.end()))
        else:
            valid.append(ParsedDate(d, m.start(), m.end(), m.group()))

    # 3. Formatted English Date
    for m in DATE_DMY_RE.finditer(text):
        m_name = m.group("month").lower()
        month_num = MONTH_NAMES.get(m_name, 0)
        d = _safe_date(int(m.group("year")), month_num, int(m.group("day")))
        if d is None:
            invalid_calendar.append((m.start(), m.end()))
        else:
            valid.append(ParsedDate(d, m.start(), m.end(), m.group()))

    for m in DATE_MDY_RE.finditer(text):
        m_name = m.group("month").lower()
        month_num = MONTH_NAMES.get(m_name, 0)
        d = _safe_date(int(m.group("year")), month_num, int(m.group("day")))
        if d is None:
            invalid_calendar.append((m.start(), m.end()))
        else:
            valid.append(ParsedDate(d, m.start(), m.end(), m.group()))

    # 4. Chinese Date
    for m in DATE_ZH_FULL_RE.finditer(text):
        d = _safe_date(int(m.group("year")), int(m.group("month")), int(m.group("day")))
        if d is None:
            invalid_calendar.append((m.start(), m.end()))
        else:
            valid.append(ParsedDate(d, m.start(), m.end(), m.group()))

    # 5. Weekdays (EN, ZH, MS)
    for m in WEEKDAY_RE.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in [(d.start, d.end) for d in valid] + invalid_calendar):
            continue
        # If part of an ambiguous phrase (e.g. "next Friday", "下周五"), do not treat as a valid resolved date
        expanded_slice = text[max(0, m.start()-10):min(len(text), m.end()+10)]
        if AMBIGUOUS_DELIVERY_RE.search(expanded_slice):
            continue

        # Check if adjacent to an already-found calendar date (e.g. "this Saturday 2026-10-24")
        adjacent_date = None
        for d in valid:
            if (0 <= d.start - m.end() <= 3 and text[m.end():d.start].strip() in ("", ",", "(", ")")) or \
               (0 <= m.start - d.end <= 3 and text[d.end():m.start].strip() in ("", ",", "(", ")")):
                adjacent_date = d
                break
        name = (m.group("name_en") or m.group("name_ms") or m.group("name_zh") or "").lower()
        if adjacent_date and name in WEEKDAY_MAP:
            stated_w = WEEKDAY_MAP[name]
            if stated_w == adjacent_date.date_val.weekday():
                adjacent_date.start = min(adjacent_date.start, m.start())
                adjacent_date.end = max(adjacent_date.end, m.end())
                adjacent_date.raw = text[adjacent_date.start:adjacent_date.end]
                continue

        if local_date is None:
            tz_required.append((m.start(), m.end()))
        else:
            if name in WEEKDAY_MAP:
                w_target = WEEKDAY_MAP[name]
                diff = (w_target - local_date.weekday()) % 7
                p_en = (m.group("prefix_en") or "").lower()
                p_zh = (m.group("prefix_zh") or "").lower()
                s_ms = (m.group("suffix_ms") or "").lower()
                if (p_en == "next" or p_zh in ("下周", "下星期") or s_ms == "depan") and diff == 0:
                    diff += 7
                d = local_date + timedelta(days=diff)
                valid.append(ParsedDate(d, m.start(), m.end(), m.group(0)))


    for pattern in (DATE_ZH_SHORT_RE, YEARLESS_DMY_RE, YEARLESS_MDY_RE, NUMERIC_DATE_RE):
        for m in pattern.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in
                   [(d.start, d.end) for d in valid] + invalid_calendar + yearless):
                continue
            yearless.append(m.span())

    valid.sort(key=lambda x: x.start)
    return valid, invalid_calendar, tz_required, yearless


def _find_all_times(text: str) -> tuple[list[ParsedTime], list[tuple[int, int]]]:
    """Capture complete time-like tokens first, then validate their ranges.

    Longer 12h tokens own their spans, preventing 3:30pm from also yielding
    03:30. Invalid tokens also own spans so no valid suffix can be salvaged.
    Bare Chinese 1..12 o'clock is ambiguous without a period and is rejected.
    """
    times: list[ParsedTime] = []
    invalid = []
    occupied = []
    for pattern in (TIME_12H_RE, TIME_ZH_RE, TIME_MS_PREFIX_RE, TIME_MS_RE, TIME_24H_RE):
        for m in pattern.finditer(text):
            if any(m.start() < end and start < m.end() for start, end in occupied):
                continue
            occupied.append(m.span())
            hour, minute = m.group("hour"), m.group("minute")
            if not hour.isascii():
                # Literal hour numerals only, preserving the original span.
                numerals = {'一':1, '二':2, '两':2, '三':3, '四':4, '五':5, '六':6, '七':7, '八':8, '九':9, '十':10,
                            **{'十'+c:10+n for c,n in zip('一二三四五六七八九',range(1,10))}, '二十':20,
                            **{'二十'+c:20+n for c,n in zip('一二三',range(1,4))}}
                if hour not in numerals:
                    invalid.append(m.span())
                    continue
                hour = str(numerals[hour])
            groups = m.groupdict()
            mer = (groups.get("meridiem") or "").lower()
            if (len(hour) > 2 or (minute is not None and len(minute) != 2)
                    or groups.get("extra") or groups.get("suffix")):
                invalid.append(m.span())
                continue
            hr = int(hour)
            mn = 30 if groups.get("half") else int(minute) if minute else 0
            bad_hour = not (1 <= hr <= 12) if mer else not (0 <= hr <= 23)
            ambiguous = (pattern is TIME_ZH_RE and ((not mer and 1 <= hr <= 12)
                or (mer == "中午" and hr != 12) or (mer in ("晚上", "早上") and hr == 12))) or (
                pattern is TIME_MS_RE and not mer and 1 <= hr <= 12
            )
            if bad_hour or not 0 <= mn <= 59 or ambiguous:
                invalid.append(m.span())
                continue
            if mer in ("pm", "ptg", "petang", "下午", "晚上", "傍晚", "malam") and hr < 12:
                hr += 12
            elif mer in ("tengah hari", "tengahhari"):
                if hr < 12:
                    hr += 12
            elif mer in ("am", "pg", "pagi", "上午", "早上") and hr == 12:
                hr = 0
            times.append(ParsedTime(hr, mn, m.start(), m.end(), m.group()))
    for m in re.finditer(r'\b(?:noon|12nn)\b', text, re.I):
        if not any(m.start() < end and start < m.end() for start,end in occupied):
            times.append(ParsedTime(12, 0, m.start(), m.end(), m.group()))
    times.sort(key=lambda x: x.start)
    return times, invalid


# ---------------------------------------------------------------------------
# Main Extraction Function
# ---------------------------------------------------------------------------


def _resolve_complex_temporal_semantics(text: str, dates_found: list[ParsedDate], times_found: list[ParsedTime],
                                        tz: ZoneInfo | None, local_dt: datetime | None):
    if not dates_found:
        return None

    if len(dates_found) == 1:
        d = dates_found[0]
        if times_found:
            t = times_found[0]
            win_start = min(d.start, t.start)
            win_end = max(d.end, t.end)
            window = text[win_start:win_end]
            pre_t = text[max(0, t.start - 15):t.start]
            post_t = text[t.end:min(len(text), t.end + 15)]
            m_approx = APPROXIMATE_MODIFIER_RE.search(window) or APPROXIMATE_MODIFIER_RE.search(pre_t) or APPROXIMATE_MODIFIER_RE.search(post_t)
            if m_approx:
                m_meal = MEAL_PERIOD_RE.search(window)
                full_start = min(d.start, t.start)
                full_end = max(d.end, t.end)
                target_iso = None
                if tz:
                    wall_dt = datetime.combine(d.date_val, time(t.hour, t.minute))
                    target_dt, _ = _unique_local_instant(wall_dt, tz)
                    if target_dt:
                        target_iso = target_dt.isoformat()

                meta = {
                    "approximate": "true",
                    "target_date": d.date_val.isoformat(),
                    "target_time": f"{t.hour:02d}:{t.minute:02d}:00",
                    "candidate_delivery_value": target_iso or "",
                    "modifier": m_approx.group().strip(),
                    "reason": f"Approximate requested delivery time '{m_approx.group().strip()} {t.raw}' on {d.date_val.isoformat()} requires operator confirmation; cannot accept as exact commitment",
                }
                if m_meal:
                    meta["meal_period"] = m_meal.group().strip()

                return {
                    "value": None,
                    "qualifier": None,
                    "target_span": (full_start, full_end),
                    "full_span": (full_start, full_end),
                    "metadata": meta,
                }
        else:
            after_date = text[d.end:min(len(text), d.end + 35)]
            m_meal = MEAL_PERIOD_RE.search(after_date)
            m_undecided = UNDECIDED_TIME_RE.search(after_date)
            if m_meal:
                full_start = d.start
                full_end = d.end + m_meal.end()
                return {
                    "value": d.date_val.isoformat(),
                    "qualifier": "DATE_ONLY",
                    "target_span": (full_start, full_end),
                    "full_span": (full_start, full_end),
                    "metadata": {
                        "meal_period": m_meal.group().strip(),
                        "target_date": d.date_val.isoformat(),
                        "qualifier": "DATE_ONLY",
                        "reason": f"Meal period '{m_meal.group().strip()}' specified without explicit clock time; manual review required",
                    },
                }
            elif m_undecided:
                full_start = d.start
                full_end = d.end + m_undecided.end()
                return {
                    "value": d.date_val.isoformat(),
                    "qualifier": "DATE_ONLY",
                    "target_span": (full_start, full_end),
                    "full_span": (full_start, full_end),
                    "metadata": {
                        "unconfirmed_time": "true",
                        "target_date": d.date_val.isoformat(),
                        "qualifier": "DATE_ONLY",
                        "reason": "Delivery date specified without confirmed delivery time; operator confirmation required",
                    },
                }

        return None

    d1, d2 = dates_found[0], dates_found[1]

    # 0. Weekday / Calendar Date conflict (e.g. "this Friday 2026-10-24")
    m_wd1 = WEEKDAY_RE.search(d1.raw)
    m_wd2 = WEEKDAY_RE.search(d2.raw)
    gap_between = text[d1.end:d2.start].strip()
    is_adjacent_pair = (d2.start - d1.end <= 3) and gap_between in ("", ",", "(", ")")
    if is_adjacent_pair and (m_wd1 or m_wd2):
        cal_date = d2 if m_wd1 else d1
        m_wd = m_wd1 or m_wd2
        name = (m_wd.group("name_en") or m_wd.group("name_ms") or m_wd.group("name_zh") or "").lower()
        if name in WEEKDAY_MAP:
            stated_w = WEEKDAY_MAP[name]
            actual_w = cal_date.date_val.weekday()
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            if stated_w != actual_w:
                assoc_time = None
                for t in times_found:
                    if (t.start >= cal_date.end and t.start - cal_date.end <= 30) or (t.end <= d1.start and d1.start - t.end <= 30):
                        assoc_time = t
                        break
                qualifier = "DATE_ONLY"
                full_end = max(d1.end, cal_date.end)
                if assoc_time is not None:
                    time_gap = text[max(d1.end, cal_date.end):assoc_time.start]
                    m_dl = DEADLINE_PRE_RE.search(time_gap) or DEADLINE_POST_RE.search(text[assoc_time.end:assoc_time.end + 15])
                    qualifier = "DEADLINE" if m_dl else "EXACT"
                    full_end = max(full_end, assoc_time.end)
                return {
                    "value": None,
                    "qualifier": qualifier,
                    "target_span": (min(d1.start, cal_date.start), max(d1.end, cal_date.end)),
                    "full_span": (min(d1.start, cal_date.start), full_end),
                    "metadata": {
                        "weekday_conflict": "true",
                        "stated_weekday": day_names[stated_w],
                        "actual_weekday": day_names[actual_w],
                        "calendar_date": cal_date.date_val.isoformat(),
                        "qualifier": qualifier,
                        "reason": f"Weekday/date conflict: {cal_date.date_val.isoformat()} is {day_names[actual_w]}, not {day_names[stated_w]}; manual review required",
                    }
                }

    pre_d1 = text[max(0, d1.start - 40):d1.start].lower()
    between = text[d1.end:d2.start].lower()

    # 1. Rescheduling: from <d1> to <d2>
    is_from_to = bool(re.search(r'\b(?:from|dari|从)\s*$', pre_d1)) and bool(re.search(r'^\s*(?:to|ke|pada|到|至)\b', between))
    is_reschedule_verb = bool(re.search(r'\b(?:moving(?:\s+the)?\s+delivery|move(?:\s+the)?\s+delivery|reschedul\w*|postpon\w*|change(?:\s+the)?\s+delivery|delay(?:\s+the)?\s+delivery|tunda|ubah|tukar|改期|更改|推迟)\b', pre_d1))
    is_instead_of = bool(re.search(r'\b(?:instead\s+of|rather\s+than|daripada|而不是)\b', between))

    # 2. Negation / Correction: not on <d1>, but on <d2>
    is_negation = bool(re.search(r'\b(?:not\s+on|not|bukan\s+pada|bukan|tidak\s+pada|不是在|不是|不要在)\b', pre_d1)) and bool(re.search(r'\b(?:but|on|deliver|hantar|改在|要在|而是)\b', between))

    # 3. Date Range: between <d1> and <d2>
    is_range = bool(re.search(r'\b(?:between|antara|在)\b', pre_d1)) and bool(re.search(r'\b(?:and|dan|到|至|与)\b', between))

    orig_date = None
    target_date = None
    mode = None

    if (is_from_to and is_reschedule_verb) or is_from_to:
        orig_date = d1
        target_date = d2
        mode = "rescheduling"
    elif is_instead_of:
        # "<target_date> instead of <orig_date>"
        target_date = d1
        orig_date = d2
        mode = "rescheduling"
    elif is_negation:
        orig_date = d1
        target_date = d2
        mode = "correction"
    elif is_range:
        mode = "date_range"
    else:
        mode = "multiple_delivery_dates"

    if mode in ("rescheduling", "correction"):
        assoc_time = None
        for t in times_found:
            if (t.start >= target_date.end and t.start - target_date.end <= 30) or (t.end <= target_date.start and target_date.start - t.end <= 30):
                assoc_time = t
                break

        qualifier = "DATE_ONLY"
        target_iso = None
        deadline_quote = ""
        target_span_start = target_date.start
        target_span_end = target_date.end

        if assoc_time is not None:
            time_gap = text[target_date.end:assoc_time.start] if assoc_time.start >= target_date.end else text[assoc_time.end:target_date.start]
            m_dl = DEADLINE_PRE_RE.search(time_gap) or DEADLINE_POST_RE.search(text[assoc_time.end:assoc_time.end + 15])
            m_ex = EXACT_INDICATOR_RE.search(time_gap)

            if m_dl:
                qualifier = "DEADLINE"
                deadline_quote = f"{m_dl.group().strip()} {assoc_time.raw}"
            elif m_ex:
                qualifier = "EXACT"
            else:
                qualifier = "EXACT"

            target_span_start = min(target_date.start, assoc_time.start)
            target_span_end = max(target_date.end, assoc_time.end)
            if m_dl and assoc_time.start >= target_date.end:
                target_span_start = target_date.start
                target_span_end = assoc_time.end

            if tz:
                wall_dt = datetime.combine(target_date.date_val, time(assoc_time.hour, assoc_time.minute))
                target_dt, _ = _unique_local_instant(wall_dt, tz)
                if target_dt:
                    target_iso = target_dt.isoformat()

        full_clause_start = min(orig_date.start, target_date.start)
        lead_from = text[max(0, full_clause_start - 8):full_clause_start]
        m_lead = re.search(r'\b(?:from|dari|not\s+on|not|bukan\s+pada|bukan|从)\s*$', lead_from, re.I)
        if m_lead:
            full_clause_start -= (len(lead_from) - m_lead.start())

        full_clause_end = max(orig_date.end, target_span_end)

        metadata = {
            "rescheduling": "true" if mode == "rescheduling" else "false",
            "correction": "true" if mode == "correction" else "false",
            "temporal_role": "requested_new_delivery",
            "original_delivery_date": orig_date.date_val.isoformat(),
            "original_delivery_quote": orig_date.raw,
            "requested_delivery_date": target_date.date_val.isoformat(),
            "requested_delivery_quote": target_date.raw,
            "qualifier": qualifier,
            "reason": f"{'Rescheduled' if mode == 'rescheduling' else 'Corrected'} delivery from {orig_date.raw} to {target_date.raw}{(' ' + deadline_quote) if deadline_quote else ''}; manual review required",
        }
        if qualifier == "DEADLINE":
            metadata["upper_bound_deadline"] = target_iso or ""
            metadata["deadline_time"] = f"{assoc_time.hour:02d}:{assoc_time.minute:02d}:00" if assoc_time else ""
            metadata["deadline_quote"] = deadline_quote

        return {
            "value": target_iso,
            "qualifier": qualifier,
            "target_span": (target_span_start, target_span_end),
            "full_span": (full_clause_start, full_clause_end),
            "metadata": metadata,
        }

    elif mode == "date_range":
        start_d, end_d = d1, d2
        full_clause_start = min(start_d.start, end_d.start)
        lead_between = text[max(0, full_clause_start - 10):full_clause_start]
        m_lead = re.search(r'\b(?:between|antara|在)\s*$', lead_between, re.I)
        if m_lead:
            full_clause_start -= (len(lead_between) - m_lead.start())
        full_clause_end = max(start_d.end, end_d.end)

        metadata = {
            "date_range": "true",
            "window_start": start_d.date_val.isoformat(),
            "window_start_quote": start_d.raw,
            "window_end": end_d.date_val.isoformat(),
            "window_end_quote": end_d.raw,
            "qualifier": "DATE_ONLY",
            "reason": f"Delivery window range from {start_d.raw} to {end_d.raw} requires operator confirmation of specific deadline",
        }
        return {
            "value": None,
            "qualifier": "DATE_ONLY",
            "target_span": (start_d.start, end_d.end),
            "full_span": (full_clause_start, full_clause_end),
            "metadata": metadata,
        }

    else:
        metadata = {
            "multiple_delivery_dates": "true",
            "reason": "Conflicting delivery date or time expressions in message; split delivery or schedule choice requires review",
        }
        return {
            "value": None,
            "qualifier": None,
            "target_span": (d1.start, d2.end),
            "full_span": (d1.start, d2.end),
            "metadata": metadata,
        }


def extract_explicit_fields(message: StoredMessage, *, catalog: Sequence[ProductAlias]) -> ExtractionResult:
    """Return literal observations only. VALID means rule-valid, not authority."""
    text = message.raw.text

    def evidence(start: int, end: int) -> FieldEvidence:
        return FieldEvidence(
            evidence_id=f"rule:{message.message_id}:{start}:{end}",
            message_id=message.message_id,
            quote=text[start:end],
            start=start,
            end=end,
            method="RULE",
            method_version=VERSION,
        )

    def field(
        name: str,
        value: str | None,
        status: str,
        spans: Sequence[tuple[int, int]] = (),
        qualifier: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ExtractedField:
        ev_list = [evidence(s, e) for s, e in spans if 0 <= s < e <= len(text)]
        return ExtractedField(
            field_name=name,
            value=value,
            validation_status=status,
            evidence=ev_list,
            qualifier=qualifier,
            metadata=metadata or {},
        )

    # -----------------------------------------------------------------------
    # 1. Order References
    # -----------------------------------------------------------------------
    orders = list(ORDER_RE.finditer(text))
    fields = [field("order_id", m.group(), "UNRESOLVED", [m.span()], metadata={"source": "purchase_order_reference"}) for m in orders]

    # Confirmation constraints are captured internally for review/approval rules,
    # never as an additional canonical extraction field.
    has_written_confirmation = bool(CONFIRMATION_CONSTRAINT_RE.search(text))

    # -----------------------------------------------------------------------
    # 2. Delivery Date & Time Extraction
    # -----------------------------------------------------------------------
    delivery_spans: list[tuple[int, int]] = []
    delivery_field: ExtractedField | None = None

    tz: ZoneInfo | None = None
    tz_error: str | None = None
    if not message.raw.business_timezone:
        tz_error = "Missing business timezone"
    else:
        try:
            tz = ZoneInfo(message.raw.business_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz_error = f"Invalid business timezone '{message.raw.business_timezone}'"

    # Source-time policy: the preserved provider message timestamp, if supplied;
    # otherwise the delivery observation timestamp. Never ingestion/processing
    # wall clock. A message timestamp later than its receipt is inconsistent.
    source_time = message.raw.message_at if message.raw.message_at is not None else message.raw.received_at
    source_kind = "message_at" if message.raw.message_at is not None else "received_at"
    source_time_error = "message_at is later than received_at; source timestamp requires review" if source_time > message.raw.received_at else None
    local_dt = source_time.astimezone(tz) if tz else None
    local_date = local_dt.date() if local_dt else None

    # Check for unsupported or ambiguous relative expressions
    ambig_match = AMBIGUOUS_DELIVERY_RE.search(text)
    dates_found, invalid_calendar_spans, tz_required_spans, yearless_spans = _find_all_dates(text, local_date)
    times_found, invalid_time_spans = _find_all_times(text)
    unsupported_semantics = None
    if dates_found or times_found:
        for m_unsupp in UNSUPPORTED_TIME_SEMANTICS_RE.finditer(text):
            if any(d.start <= m_unsupp.start() and m_unsupp.end() <= d.end for d in dates_found):
                continue
            unsupported_semantics = m_unsupp
            break
    # Exclude every recognized temporal token from quantity candidates, even
    # when delivery is invalid/unresolved. Do not steal dates as order counts.
    delivery_spans.extend([(d.start, d.end) for d in dates_found]
                          + [(t.start, t.end) for t in times_found]
                          + invalid_calendar_spans + invalid_time_spans + tz_required_spans + yearless_spans)

    # Detect conflicts: multiple dates or times with connector
    has_conflict = False
    conflict_span: tuple[int, int] | None = None
    if len(dates_found) > 1:
        has_conflict = True
        conflict_span = (dates_found[0].start, dates_found[-1].end)
    elif len(times_found) > 1:
        has_conflict = True
        conflict_span = (times_found[0].start, times_found[-1].end)
    elif dates_found and times_found:
        dt, tm = dates_found[0], times_found[0]
        gap = text[min(dt.end, tm.end):max(dt.start, tm.start)]
        if re.search(r"[;。.!?！？\n]", gap):
            has_conflict = True
            conflict_span = (min(dt.start, tm.start), max(dt.end, tm.end))

    sem_temporal = _resolve_complex_temporal_semantics(text, dates_found, times_found, tz, local_dt)
    if sem_temporal is not None:
        delivery_spans.extend([sem_temporal["target_span"], sem_temporal["full_span"]])
        ev_spans = [sem_temporal["target_span"]]
        if sem_temporal["full_span"] != sem_temporal["target_span"]:
            ev_spans.append(sem_temporal["full_span"])
        delivery_field = field(
            "requested_delivery_at",
            sem_temporal["value"],
            "UNRESOLVED",
            ev_spans,
            qualifier=sem_temporal["qualifier"],
            metadata=sem_temporal["metadata"],
        )
    elif unsupported_semantics:
        spans = delivery_spans + [unsupported_semantics.span()]
        span = (min(s for s, e in spans), max(e for s, e in spans))
        delivery_spans.append(span)
        delivery_field = field("requested_delivery_at", None, "UNRESOLVED", [span],
                               metadata={"reason": "Unsupported delivery bound, range, approximation or explicit timezone; manual review required"})
    elif invalid_time_spans:
        delivery_field = field("requested_delivery_at", None, "INVALID", invalid_time_spans,
                               metadata={"reason": "Invalid or ambiguous time expression; no partial time or date-only fallback"})
    elif has_conflict and conflict_span:
        c_start, c_end = conflict_span
        delivery_spans.append((c_start, c_end))
        delivery_field = field(
            "requested_delivery_at",
            None,
            "UNRESOLVED",
            [(c_start, c_end)],
            metadata={"reason": "Conflicting delivery date or time expressions in message"},
        )
    elif ambig_match:
        a_start, a_end = ambig_match.span()
        delivery_spans.append((a_start, a_end))
        delivery_field = field(
            "requested_delivery_at",
            None,
            "UNRESOLVED",
            [(a_start, a_end)],
            metadata={"reason": "Unsupported or ambiguous natural-language delivery expression; manual review required"},
        )
    elif invalid_calendar_spans:
        err_span = invalid_calendar_spans[0]
        delivery_spans.append(err_span)
        delivery_field = field(
            "requested_delivery_at",
            None,
            "INVALID",
            [err_span],
            metadata={"reason": "Impossible calendar date"},
        )
    elif source_time_error and delivery_spans:
        delivery_field = field("requested_delivery_at", None, "UNRESOLVED", delivery_spans,
                               metadata={"reason": source_time_error})
    elif yearless_spans:
        delivery_field = field("requested_delivery_at", None, "UNRESOLVED", yearless_spans,
                               metadata={"reason": "Yearless or ambiguous numeric date; explicit year and unambiguous format required"})
    elif tz is None and delivery_spans:
        delivery_field = field("requested_delivery_at", None, "UNRESOLVED", delivery_spans,
                               metadata={"reason": tz_error or "Missing business timezone"})
    elif dates_found:
        parsed_date = dates_found[0]
        parsed_time = times_found[0] if times_found else None

        span_start = parsed_date.start
        span_end = parsed_date.end
        qualifier = "EXACT"

        if parsed_time is not None:
            span_start = min(span_start, parsed_time.start)
            span_end = max(span_end, parsed_time.end)

        # Surrounding context check
        pre_start = max(0, span_start - 20)
        pre_text = text[pre_start:span_start]
        post_end = min(len(text), span_end + 15)
        post_text = text[span_end:post_end]

        in_between = ""
        if parsed_time and parsed_date:
            gap_start = min(parsed_date.end, parsed_time.end)
            gap_end = max(parsed_date.start, parsed_time.start)
            if gap_start < gap_end:
                in_between = text[gap_start:gap_end]

        m_pre = DEADLINE_PRE_RE.search(pre_text)
        m_post = DEADLINE_POST_RE.search(post_text)
        m_in = DEADLINE_PRE_RE.search(in_between)

        if m_pre:
            qualifier = "DEADLINE"
            span_start = pre_start + m_pre.start()
        elif m_in:
            qualifier = "DEADLINE"
        elif m_post:
            qualifier = "DEADLINE"
            span_end = span_end + m_post.end()
        elif EXACT_INDICATOR_RE.search(pre_text):
            m_exact = EXACT_INDICATOR_RE.search(pre_text)
            if m_exact:
                span_start = pre_start + m_exact.start()

        # Leading connector word (on, by, before, at)
        lead_slice = text[max(0, span_start - 12):span_start]
        m_lead = re.search(r"\b(?:on|by|before|at|pada|sebelum|untuk)\s+$", lead_slice, re.IGNORECASE)
        if m_lead:
            span_start = span_start - (len(lead_slice) - m_lead.start())

        delivery_spans.append((span_start, span_end))

        if parsed_time is not None:
            if tz is None:
                delivery_field = field(
                    "requested_delivery_at",
                    None,
                    "UNRESOLVED",
                    [(span_start, span_end)],
                    qualifier=qualifier,
                    metadata={"reason": tz_error or "Missing timezone"},
                )
            else:
                wall = datetime(
                    parsed_date.date_val.year,
                    parsed_date.date_val.month,
                    parsed_date.date_val.day,
                    parsed_time.hour,
                    parsed_time.minute,
                )
                combined, instant_error = _unique_local_instant(wall, tz)
                if instant_error:
                    delivery_field = field("requested_delivery_at", None, "UNRESOLVED", [(span_start, span_end)],
                                           metadata={"reason": instant_error})
                else:
                    delivery_field = field(
                        "requested_delivery_at", combined.isoformat(), "VALID", [(span_start, span_end)],
                        qualifier=qualifier,
                        metadata={"qualifier": qualifier, "raw_expression": text[span_start:span_end],
                                  "timezone": message.raw.business_timezone or "",
                                  "local_time": combined.strftime("%Y-%m-%d %H:%M:%S")},
                    )
                    if combined.astimezone(timezone.utc) < message.raw.received_at.astimezone(timezone.utc):
                        delivery_field.metadata.update(reason="Delivery is in the past relative to received_at; delayed/historical requests require review",
                                                       candidate_delivery_value=delivery_field.value)
                        delivery_field.validation_status = "UNRESOLVED"
                        delivery_field.value = None
        else:
            date_relation = qualifier
            qualifier = "DATE_ONLY"
            delivery_field = field(
                "requested_delivery_at",
                parsed_date.date_val.isoformat(),
                "VALID",
                [(span_start, span_end)],
                qualifier=qualifier,
                metadata={
                    "qualifier": qualifier,
                    "date_relation": date_relation,
                    "raw_expression": text[span_start:span_end],
                    "timezone": message.raw.business_timezone or "",
                },
            )
            # Date-only is compared as a business calendar date, not midnight.
            # No current wall clock or automatic roll-forward is used.
            if tz and parsed_date.date_val < message.raw.received_at.astimezone(tz).date():
                delivery_field.metadata.update(reason="Delivery date is in the past relative to received_at; manual review required",
                                               candidate_delivery_value=delivery_field.value)
                delivery_field.validation_status = "UNRESOLVED"
                delivery_field.value = None
    elif times_found:
        pt = times_found[0]
        delivery_spans.append((pt.start, pt.end))
        delivery_field = field(
            "requested_delivery_at",
            None,
            "UNRESOLVED",
            [(pt.start, pt.end)],
            metadata={"reason": "Time specified without delivery date; ambiguous"},
        )

    if delivery_field is None:
        delivery_field = field("requested_delivery_at", None, "MISSING")

    if has_written_confirmation:
        m_conf = CONFIRMATION_CONSTRAINT_RE.search(text)
        delivery_field.metadata["requires_written_confirmation"] = "true"
        if m_conf:
            delivery_field.metadata["confirmation_constraint"] = m_conf.group(0)

    if delivery_field.validation_status != "MISSING":
        if message.raw.received_at > message.ingested_at and delivery_field.validation_status == "VALID":
            delivery_field.metadata.update(reason="Source receipt is later than server persistence; review clock provenance",
                                           candidate_delivery_value=delivery_field.value or "")
            delivery_field.validation_status = "UNRESOLVED"
            delivery_field.value = None
        delivery_field.metadata.update({
            "source_timestamp_policy": "message_at_else_received_at_v1",
            "source_timestamp_source": source_kind,
            "source_timestamp": source_time.isoformat(),
            "received_at": message.raw.received_at.isoformat(),
            "past_validation_reference": "received_at",
            "timezone_source": "message.business_timezone" if message.raw.business_timezone else "missing",
        })

        if delivery_field.validation_status == "VALID":
            delivery_field.metadata["resolved_by_rule"] = "true"

    fields.append(delivery_field)

    # -----------------------------------------------------------------------
    # 3. Known SKU Mention Matching
    # -----------------------------------------------------------------------
    # Non-alphanumeric boundaries allow Chinese characters to boundary-match English SKUs
    ALIAS_BOUNDARY_PRE = r"(?<![A-Za-z0-9_])"
    ALIAS_BOUNDARY_POST = r"(?![A-Za-z0-9_])"

    mentions = []
    for product in catalog:
        if product.tenant_id != message.raw.tenant_id:
            continue
        sorted_aliases = sorted(product.aliases, key=len, reverse=True)
        for alias in sorted_aliases:
            is_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in alias)
            pre = "" if is_cjk else ALIAS_BOUNDARY_PRE
            post = "" if is_cjk else ALIAS_BOUNDARY_POST
            for match in re.finditer(pre + re.escape(alias) + post, text, re.IGNORECASE):
                key = (match.start(), match.end(), product.sku, product.unit)
                if not any(key == entry[0] for entry in mentions):
                    mentions.append((key, product, match))
    pruned_mentions = []
    for entry in mentions:
        _, prod, m = entry
        if any(other[2].start() <= m.start() and m.end() <= other[2].end() and (other[2].end() - other[2].start()) > (m.end() - m.start()) for other in mentions):
            continue
        pruned_mentions.append(entry)
    mentions = pruned_mentions
    mentions.sort(key=lambda entry: entry[0])

    # -----------------------------------------------------------------------
    # 4. Quantity and Unit Association
    # -----------------------------------------------------------------------
    PACKAGING_SPEC_RE = re.compile(
        r'\b(?:pack(?:ed)?(?:\s+into|\s+in)?|packing)\s+(?P<boxes>[0-9]+)\s+(?:separate\s+)?(?P<box_unit>boxes|box|packs|pack|cartons|carton|bags|bag|trays|tray|kotak|bungkus)(?:\s+of\s+(?P<per_box>[0-9]+)\s*(?P<unit>[A-Za-z]+)?(?:\s+each)?)?\b|'
        r'\b(?P<p_per_box>[0-9]+)\s*(?P<p_unit>[A-Za-z]+)?\s+(?:per|each|setiap)\s+(?P<p_box_unit>box|boxes|carton|cartons|kotak|bungkus)\b',
        re.IGNORECASE
    )
    packaging_spans = [m.span() for m in PACKAGING_SPEC_RE.finditer(text)]
    packaging_match = PACKAGING_SPEC_RE.search(text)

    # Numbers that fall inside orders, delivery spans, or packaging breakdowns are excluded from quantity candidates
    non_quantity_spans = [o.span() for o in orders] + delivery_spans + packaging_spans
    non_quantity_spans += [m.span() for m in re.finditer(
        r"\b(?:phone|tel|reference|ref)\s*[:#]?\s*[0-9]+\b|"
        r"\bpukul\s+[0-9]+(?::[0-9]+)?\s*(?:pagi|petang|malam)\b", text, re.IGNORECASE)]

    numbers = [
        m for m in NUMBER_RE.finditer(text)
        if not any(s <= m.start() and m.end() <= e for s, e in non_quantity_spans)
    ]

    if not mentions:
        fields.extend([
            field("sku", None, "UNRESOLVED"),
            field("quantity", None, "UNRESOLVED" if numbers else "MISSING", [m.span() for m in numbers]),
        ])
    else:
        for idx, (_, product, mention) in enumerate(mentions, start=1):
            ambiguous = any(
                other.start() < mention.end() and mention.start() < other.end()
                and (candidate.sku, candidate.unit) != (product.sku, product.unit)
                for _, candidate, other in mentions
            )
            pre_context = text[max(0, mention.start()-25):mention.start()]
            is_negated = bool(re.search(r"\b(?:cancel|tak\s+nak|jangan\s+hantar|jangan\s+buat|do\s+not\s+send)\b|不要送|不要|取消", pre_context, re.I))
            status = "UNRESOLVED" if (ambiguous or is_negated) else "VALID"
            meta = {"group_id": f"g{idx}"}
            if is_negated:
                meta["reason"] = "Mention preceded by cancellation keyword"
            elif ambiguous:
                meta["reason"] = "Catalog alias maps to multiple SKU/unit meanings"
            else:
                meta["resolved_by_rule"] = "true"
            fields.append(field("sku", product.sku, status, [mention.span()], metadata=meta))

        _, product, mention = mentions[0]
        prefix = CONTAINING_PREFIX_RE.search(text[:mention.start()])
        if prefix:
            packaging_spans.append(prefix.span("per_box"))
            non_quantity_spans.append(prefix.span("per_box"))
            numbers = [m for m in numbers if not (prefix.span("per_box")[0] <= m.start() and m.end() <= prefix.span("per_box")[1])]
        else:
            prefix = QUANTITY_PREFIX_RE.search(text[:mention.start()])

        association_text = text
        explicit_amendment = bool(re.search(r'\b(?:change|amend|revise|update)\b.{0,45}\bto\s+[0-9]|\btukar\b.{0,30}\bkepada\s+[0-9]|(?:改为|改成)\s*[0-9]', text, re.I))
        if explicit_amendment and len(numbers) == len(mentions) == 1:
            association_text = re.sub(r'\binstead\b', '', text, flags=re.I)

        # Scope unsafe association check to the sentence or clause containing the mention
        sent_start = max([text.rfind(c, 0, mention.start()) for c in ('.', '!', '?', ';', '\n')] + [0])
        if sent_start > 0:
            sent_start += 1
        sent_end = min([pos for c in ('.', '!', '?', ';', '\n') if (pos := text.find(c, mention.end())) != -1] + [len(text)])
        item_clause = association_text[sent_start:sent_end]
        unsafe_matches = [
            m for m in UNSAFE_ASSOCIATION_RE.finditer(item_clause)
            if not any(s <= (sent_start + m.start()) and (sent_start + m.end()) <= e for s, e in delivery_spans + packaging_spans)
        ]
        if len(mentions) != 1 or unsafe_matches or len(numbers) > 1:
            fields.append(field("quantity", None, "UNRESOLVED", [m.span() for m in numbers]))
        elif prefix is None or len(numbers) != 1 or prefix.span("quantity") != numbers[0].span():
            fields.append(field("quantity", None, "UNRESOLVED" if numbers else "MISSING", [m.span() for m in numbers]))
        else:
            raw_quantity = prefix.group("quantity")
            raw_unit = prefix.group("unit")

            # Check packaging breakdown consistency if unit was not prefixed
            if packaging_match and not raw_unit and packaging_match.group("boxes") and packaging_match.group("per_box"):
                p_boxes = int(packaging_match.group("boxes"))
                p_per_box = int(packaging_match.group("per_box"))
                p_unit = (packaging_match.group("unit") or "").lower()
                if p_unit in UNIT_NORMALIZATION:
                    p_unit = UNIT_NORMALIZATION[p_unit]
                if p_boxes * p_per_box == int(raw_quantity) and p_unit:
                    raw_unit = p_unit

            # Unit normalization
            norm_unit = UNIT_NORMALIZATION.get(raw_unit.lower()) if raw_unit else None
            effective_catalog = PROVISIONAL_PRODUCTS if catalog is None else catalog
            tenant_sku_units = {
                p.unit for p in effective_catalog
                if p.tenant_id == message.raw.tenant_id and p.sku == product.sku
            }
            if not tenant_sku_units:
                tenant_sku_units = {product.unit}
            unit_supported = (norm_unit in tenant_sku_units) if raw_unit else ("pcs" in tenant_sku_units)

            valid_qty = raw_quantity.isascii() and raw_quantity.isdigit() and Decimal(raw_quantity) > 0

            unit_spans = [prefix.span("unit")] if prefix.group("unit") else (
                [packaging_match.span("unit")] if (packaging_match and packaging_match.group("unit")) else []
            )

            if raw_unit is not None and not unit_supported:
                # Incompatible packaging unit: preserve explicit quantity and unit as INVALID in literal rules
                # (Reconciled to UNRESOLVED for operational use).
                fields.append(field(
                    "quantity",
                    raw_quantity,
                    "INVALID",
                    [prefix.span("quantity")],
                    metadata={
                        "group_id": f"g1",
                        "domain_supported": "false",
                        "disposition": "unverified_association",
                        "reason": f"Unit '{norm_unit or raw_unit}' unsupported for SKU '{product.sku}'",
                    },
                ))
                fields.append(field(
                    "unit",
                    norm_unit or raw_unit,
                    "INVALID",
                    unit_spans,
                    metadata={
                        "group_id": f"g1",
                        "raw_unit": raw_unit,
                        "normalized_unit": norm_unit or raw_unit,
                        "domain_supported": "false",
                        "disposition": "unverified_association",
                        "reason": f"Unit '{raw_unit}' unsupported for SKU '{product.sku}'",
                    },
                ))
            elif raw_unit is None:
                # Genuinely omitted unit remains MISSING without inventing pcs
                fields.append(field(
                    "quantity",
                    raw_quantity,
                    "VALID" if valid_qty else "INVALID",
                    [prefix.span("quantity")],
                    metadata={"group_id": f"g1", "resolved_by_rule": "true"} if valid_qty else {"group_id": f"g1"},
                ))
                fields.append(field("unit", None, "MISSING", [], metadata={"group_id": f"g1"}))
            else:
                fields.append(field(
                    "quantity",
                    raw_quantity,
                    "VALID" if valid_qty else "INVALID",
                    [prefix.span("quantity")],
                    metadata={"group_id": f"g1", "resolved_by_rule": "true"} if valid_qty else {"group_id": f"g1"},
                ))
                fields.append(field(
                    "unit",
                    norm_unit,
                    "VALID",
                    unit_spans,
                    metadata={"group_id": f"g1", "raw_unit": raw_unit, "normalized_unit": norm_unit or "", "resolved_by_rule": "true"},
                ))

    # Preserve unfamiliar nouns as observations even when the worker is offline.
    # These values are deliberately not canonical inventory items.
    from .unknown_products import literal_product_observations
    for item in literal_product_observations(text, catalog=catalog, tenant_id=message.raw.tenant_id,
                                             units=UNIT_NORMALIZATION, excluded_spans=non_quantity_spans):
        approved = item['approved']
        if approved and any(f.field_name == 'quantity' and f.value is not None and
                            any((ev.start, ev.end) == item['quantity_span'] for ev in f.evidence) for f in fields):
            continue
        group = item['group_id']
        if approved:
            group = next((f.metadata.get('group_id', group) for f in fields if f.field_name == 'sku' and
                          any(item['product_span'][0] <= ev.start < ev.end <= item['product_span'][1] for ev in f.evidence)), group)
        meta = {"group_id": group, "domain_supported": "true" if approved else "false",
                "disposition": "proposal" if approved else "unverified_product",
                "reason": "Literal item observation pending association/unit review" if approved else
                          "Unknown product; map to an approved SKU or leave unresolved"}
        if not approved:
            fields.append(field('sku', item['product'], 'UNRESOLVED', [item['product_span']], metadata=meta.copy()))
        raw_unit = item['unit']
        normalized_unit = UNIT_NORMALIZATION.get(raw_unit.lower()) if raw_unit else None
        item_meta = meta.copy()
        if approved and raw_unit and normalized_unit != approved.unit:
            item_meta.update(domain_supported='false', disposition='unverified_association',
                             reason='Unit/SKU compatibility unverified; no automatic conversion')
        fields.append(field('quantity', item['quantity'], 'UNRESOLVED', [item['quantity_span']], metadata=item_meta.copy()))
        fields.append(field('unit', normalized_unit,
                            'UNRESOLVED' if raw_unit else 'MISSING',
                            [item['unit_span']] if raw_unit else [], metadata=item_meta.copy()))

    intent = request_intent(text)
    if intent != 'UNCLASSIFIED':
        for observation in fields:
            observation.metadata['request_intent'] = intent
            if observation.validation_status == 'VALID':
                observation.validation_status = 'UNRESOLVED'
                observation.metadata['reason'] = f'{intent}: observed terms are not an established current request; review required'

    return ExtractionResult(
        status="AVAILABLE",
        fields=fields,
        reason="Deterministic observations extracted; identity, order authorization and delivery details; manual review required",
    )
