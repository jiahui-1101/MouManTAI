"""Deterministic L0 extraction rules over StoredMessage.

Extracts explicit order references, known SKUs, quantities, normalized units,
and timezone-aware delivery dates/deadlines. All observations preserve exact
Unicode code-point evidence spans [start, end) against the original text.
Unresolved, invalid, or conflicting terms remain proposed and require manual review.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import re
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .extraction import ExtractionResult
from .ingestion_schemas import StoredMessage
from .schemas import ExtractedField, FieldEvidence

VERSION = "p1-deterministic-v4"

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
    ProductAlias(tenant, "BURGER", ("burger", "burgers", "beef burger", "beef burgers", "chicken burger", "chicken burgers"), "pcs")
    for tenant in ("synthetic_tenant_a", "synthetic_tenant_b")
)

UNIT_NORMALIZATION: dict[str, str] = {
    # pieces family (EN, ZH, MS)
    "pc": "pcs",
    "pcs": "pcs",
    "piece": "pcs",
    "pieces": "pcs",
    "个": "pcs",
    "件": "pcs",
    "biji": "pcs",
    "buah": "pcs",
    "bungkus": "pcs",
    "paket": "pcs",
    # box family (EN, ZH, MS)
    "box": "box",
    "boxes": "box",
    "盒": "box",
    "箱": "box",
    "kotak": "box",
    # kg family
    "kg": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "公斤": "kg",
}

# ---------------------------------------------------------------------------
# Regular Expressions
# ---------------------------------------------------------------------------

ORDER_RE = re.compile(r"(?<![A-Za-z0-9_])(?:ORD-[0-9]+|synthetic_order_[a-z0-9]+)(?![A-Za-z0-9_])", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.,+\-])[+\-]?[0-9]+(?:[.,][0-9]+)?(?![A-Za-z0-9_.,])")

# Quantity + optional unit prefix before product mention
QUANTITY_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9_.,+\-])(?P<quantity>[+\-]?[0-9]+(?:[.,][0-9]+)?)"
    r"(?:\s*(?P<unit>[A-Za-z]+|[\u4e00-\u9fff]))?\s*$"
)

UNSAFE_ASSOCIATION_RE = re.compile(
    r"\b(?:and|or|dan|atau|not|no|cancel|instead|sorry|correction|jangan|batal)\b|和|或|不要|改成|取消",
    re.IGNORECASE
)

# Ambiguous / unsupported relative expressions that must be marked UNRESOLVED
AMBIGUOUS_DELIVERY_RE = re.compile(
    r"\b(?:next\s+(?:friday|monday|tuesday|wednesday|thursday|saturday|sunday|week|month)|"
    r"this\s+(?:friday|monday|tuesday|wednesday|thursday|saturday|sunday|weekend)|"
    r"asap|as\s+soon\s+as\s+possible|soon|same\s+as\s+last\s+time)\b|"
    r"(?:下周[一二三四五六日七]?|下个星期[一二三四五六天]?|这周末|下个月|尽快|马上|越快越好|老样子|照旧)",
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

# Time patterns
TIME_12H_RE = re.compile(
    r"(?<![A-Za-z0-9_:])(?P<hour>[0-9]+)(?:[:.](?P<minute>[0-9]+))?"
    r"(?P<extra>(?::[0-9]+)*)\s*(?P<meridiem>am|pm)(?P<suffix>[A-Za-z0-9_]*)(?![A-Za-z0-9_:])",
    re.IGNORECASE
)
TIME_24H_RE = re.compile(
    r"(?<![A-Za-z0-9_:])(?P<hour>[0-9]+):(?P<minute>[0-9]+)"
    r"(?P<extra>(?::[0-9]+)*)(?P<suffix>[A-Za-z_]*)(?![A-Za-z0-9_:])"
)
TIME_ZH_RE = re.compile(
    r"(?<![0-9])(?:(?P<meridiem>下午|晚上|上午|早上|中午|傍晚)\s*)?"
    r"(?P<hour>[0-9]+)\s*(?:点|时)(?:(?P<minute>[0-9]+)分?|(?P<half>半))?(?P<extra>[0-9]+秒)?"
)
TIME_MS_RE = re.compile(
    r"\b(?:pukul|jam)\s+(?P<hour>[0-9]+)(?:[:.](?P<minute>[0-9]+))?"
    r"(?:\s*(?P<meridiem>pagi|tengah\s+hari|petang|malam))?\b",
    re.IGNORECASE
)

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
    for pattern in (TIME_12H_RE, TIME_ZH_RE, TIME_MS_RE, TIME_24H_RE):
        for m in pattern.finditer(text):
            if any(m.start() < end and start < m.end() for start, end in occupied):
                continue
            occupied.append(m.span())
            hour, minute = m.group("hour"), m.group("minute")
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
            if mer in ("pm", "下午", "晚上", "傍晚", "petang", "malam") and hr < 12:
                hr += 12
            elif mer in ("tengah hari", "tengahhari"):
                if hr < 12:
                    hr += 12
            elif mer in ("am", "上午", "早上", "pagi") and hr == 12:
                hr = 0
            times.append(ParsedTime(hr, mn, m.start(), m.end(), m.group()))
    times.sort(key=lambda x: x.start)
    return times, invalid


# ---------------------------------------------------------------------------
# Main Extraction Function
# ---------------------------------------------------------------------------

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
    fields = [field("order_id", m.group(), "UNRESOLVED", [m.span()]) for m in orders]

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

    if unsupported_semantics:
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
            for match in re.finditer(ALIAS_BOUNDARY_PRE + re.escape(alias) + ALIAS_BOUNDARY_POST, text, re.IGNORECASE):
                key = (match.start(), match.end(), product.sku, product.unit)
                if not any(key == entry[0] for entry in mentions):
                    mentions.append((key, product, match))
    pruned_mentions = []
    for entry in mentions:
        _, prod, m = entry
        if any(other[1].sku == prod.sku and other[2].start() <= m.start() and m.end() <= other[2].end() and (other[2].end() - other[2].start()) > (m.end() - m.start()) for other in mentions):
            continue
        pruned_mentions.append(entry)
    mentions = pruned_mentions
    mentions.sort(key=lambda entry: entry[0])
    for _, product, mention in mentions:
        ambiguous = any(
            other.start() < mention.end() and mention.start() < other.end()
            and (candidate.sku, candidate.unit) != (product.sku, product.unit)
            for _, candidate, other in mentions
        )
        fields.append(field("sku", product.sku, "UNRESOLVED" if ambiguous else "VALID", [mention.span()],
                            metadata={"reason": "Catalog alias maps to multiple SKU/unit meanings"} if ambiguous else {}))

    # -----------------------------------------------------------------------
    # 4. Quantity and Unit Association
    # -----------------------------------------------------------------------
    # Numbers that fall inside orders or delivery spans are excluded from quantity candidates
    non_quantity_spans = [o.span() for o in orders] + delivery_spans
    # Explicitly labelled non-item numbers only. Unlabelled numbers still block
    # single-item association; do not simply select the nearest/first number.
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
        _, product, mention = mentions[0]
        prefix = QUANTITY_PREFIX_RE.search(text[:mention.start()])

        if len(mentions) != 1 or UNSAFE_ASSOCIATION_RE.search(text) or len(numbers) > 1:
            fields.append(field("quantity", None, "UNRESOLVED", [m.span() for m in numbers]))
        elif prefix is None or len(numbers) != 1 or prefix.span("quantity") != numbers[0].span():
            fields.append(field("quantity", None, "UNRESOLVED" if numbers else "MISSING", [m.span() for m in numbers]))
        else:
            raw_quantity = prefix.group("quantity")
            raw_unit = prefix.group("unit")

            # Unit normalization
            norm_unit = UNIT_NORMALIZATION.get(raw_unit.lower()) if raw_unit else None
            unit_supported = (norm_unit == product.unit) if raw_unit else (product.unit == "pcs")

            valid_qty = raw_quantity.isascii() and raw_quantity.isdigit() and Decimal(raw_quantity) > 0
            qty_status = "VALID" if valid_qty and unit_supported else "INVALID"

            fields.append(field(
                "quantity",
                raw_quantity,
                qty_status,
                [prefix.span("quantity")],
            ))

            if raw_unit is None:
                fields.append(field("unit", None, "MISSING", []))
            elif unit_supported:
                fields.append(field(
                    "unit",
                    norm_unit,
                    "VALID",
                    [prefix.span("unit")],
                    metadata={"raw_unit": raw_unit, "normalized_unit": norm_unit or ""},
                ))
            else:
                fields.append(field(
                    "unit",
                    raw_unit,
                    "INVALID",
                    [prefix.span("unit")],
                    metadata={"raw_unit": raw_unit, "reason": f"Unit '{raw_unit}' unsupported for SKU '{product.sku}'"},
                ))

    return ExtractionResult(
        status="AVAILABLE",
        fields=fields,
        reason="Deterministic observations extracted; identity, order authorization and delivery details; manual review required",
    )
