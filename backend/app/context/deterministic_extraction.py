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

VERSION = "p1-deterministic-v2"

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
    ProductAlias(tenant, "BURGER", ("burger", "burgers"), "pcs")
    for tenant in ("synthetic_tenant_a", "synthetic_tenant_b")
)

UNIT_NORMALIZATION: dict[str, str] = {
    # pieces family
    "pc": "pcs",
    "pcs": "pcs",
    "piece": "pcs",
    "pieces": "pcs",
    "个": "pcs",
    "件": "pcs",
    # box family
    "box": "box",
    "boxes": "box",
    "盒": "box",
    "箱": "box",
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
    r"\b(?:and|or|dan|atau|not|no|cancel|instead)\b|[,;/]|和|或|不要|改成",
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

# Relative dates
REL_DATE_EN_RE = re.compile(r"\b(?P<rel>today|tomorrow)\b", re.IGNORECASE)
REL_DATE_ZH_RE = re.compile(r"(?P<rel>今天|明天|后天)")

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

# Time patterns
TIME_12H_RE = re.compile(
    r"\b(?P<hour>1[0-2]|0?[1-9])(?::(?P<minute>[0-5]\d))?\s*(?P<meridiem>am|pm)(?![A-Za-z0-9_])",
    re.IGNORECASE
)
TIME_24H_RE = re.compile(
    r"(?<![\d:])(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)(?![\d:])"
)
TIME_ZH_RE = re.compile(
    r"(?:(?P<meridiem>下午|晚上|上午|早上|中午)\s*)?(?P<hour>1[0-2]|0?[1-9]|1\d|2[0-3])\s*(?:点|时)(?:(?P<minute>[0-5]\d)分?|(?P<half>半))?"
)

# Deadline indicators
DEADLINE_PRE_RE = re.compile(
    r"\b(?:before|by|no\s+later\s+than|prior\s+to|until)\b|(?:最晚|不迟于)",
    re.IGNORECASE
)
DEADLINE_POST_RE = re.compile(r"^(?:之前|前)")
EXACT_INDICATOR_RE = re.compile(r"\b(?:at|on|for|precisely)\b|在|于", re.IGNORECASE)

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


def _find_all_dates(text: str, local_date: date | None) -> tuple[list[ParsedDate], list[tuple[int, int]], list[tuple[int, int]]]:
    """Find all dates in text. Returns (valid_dates, invalid_calendar_date_spans, timezone_required_spans)."""
    valid: list[ParsedDate] = []
    invalid_calendar: list[tuple[int, int]] = []
    tz_required: list[tuple[int, int]] = []

    # 1. Relative dates
    for m in REL_DATE_EN_RE.finditer(text):
        if local_date is None:
            tz_required.append((m.start(), m.end()))
        else:
            rel = m.group("rel").lower()
            d = local_date + timedelta(days=1) if rel == "tomorrow" else local_date
            valid.append(ParsedDate(d, m.start(), m.end(), m.group()))

    for m in REL_DATE_ZH_RE.finditer(text):
        if local_date is None:
            tz_required.append((m.start(), m.end()))
        else:
            rel = m.group("rel")
            delta = 2 if rel == "后天" else 1 if rel == "明天" else 0
            valid.append(ParsedDate(local_date + timedelta(days=delta), m.start(), m.end(), m.group()))

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

    for m in DATE_ZH_SHORT_RE.finditer(text):
        yr = local_date.year if local_date else 2026
        d = _safe_date(yr, int(m.group("month")), int(m.group("day")))
        if d is None:
            invalid_calendar.append((m.start(), m.end()))
        else:
            valid.append(ParsedDate(d, m.start(), m.end(), m.group()))

    valid.sort(key=lambda x: x.start)
    return valid, invalid_calendar, tz_required


def _find_all_times(text: str) -> list[ParsedTime]:
    times: list[ParsedTime] = []

    # 1. 12-hour English time: 3pm, 3:30pm
    for m in TIME_12H_RE.finditer(text):
        hr = int(m.group("hour"))
        mn = int(m.group("minute")) if m.group("minute") else 0
        mer = m.group("meridiem").lower()
        if mer == "pm" and hr < 12:
            hr += 12
        elif mer == "am" and hr == 12:
            hr = 0
        times.append(ParsedTime(hr, mn, m.start(), m.end(), m.group()))

    # 2. Chinese time: 下午3点, 3点半, 下午3点前
    for m in TIME_ZH_RE.finditer(text):
        hr = int(m.group("hour"))
        mn = 30 if m.group("half") else int(m.group("minute")) if m.group("minute") else 0
        mer = m.group("meridiem")
        if mer in ("下午", "晚上") and hr < 12:
            hr += 12
        elif mer in ("上午", "早上") and hr == 12:
            hr = 0
        times.append(ParsedTime(hr, mn, m.start(), m.end(), m.group()))

    # 3. 24-hour time: 15:00
    for m in TIME_24H_RE.finditer(text):
        hr = int(m.group("hour"))
        mn = int(m.group("minute"))
        if 0 <= hr <= 23 and 0 <= mn <= 59:
            times.append(ParsedTime(hr, mn, m.start(), m.end(), m.group()))

    times.sort(key=lambda x: x.start)
    return times


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

    local_dt = message.raw.received_at.astimezone(tz) if tz else None
    local_date = local_dt.date() if local_dt else None

    # Check for unsupported or ambiguous relative expressions
    ambig_match = AMBIGUOUS_DELIVERY_RE.search(text)
    dates_found, invalid_calendar_spans, tz_required_spans = _find_all_dates(text, local_date)
    times_found = _find_all_times(text)

    # Detect conflicts: multiple dates or times with connector
    has_conflict = False
    conflict_span: tuple[int, int] | None = None
    if len(dates_found) > 1 and DELIVERY_CONFLICT_CONNECTOR_RE.search(text):
        has_conflict = True
        conflict_span = (dates_found[0].start, dates_found[-1].end)
    elif len(times_found) > 1 and DELIVERY_CONFLICT_CONNECTOR_RE.search(text):
        has_conflict = True
        conflict_span = (times_found[0].start, times_found[-1].end)

    if has_conflict and conflict_span:
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
    elif tz_required_spans and tz is None:
        err_span = tz_required_spans[0]
        delivery_spans.append(err_span)
        delivery_field = field(
            "requested_delivery_at",
            None,
            "UNRESOLVED",
            [err_span],
            metadata={"reason": f"{tz_error or 'Missing timezone'}; relative date cannot be resolved"},
        )
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
        lead_slice = text[max(0, span_start - 8):span_start]
        m_lead = re.search(r"\b(?:on|by|before|at)\s+$", lead_slice, re.IGNORECASE)
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
                combined = datetime(
                    parsed_date.date_val.year,
                    parsed_date.date_val.month,
                    parsed_date.date_val.day,
                    parsed_time.hour,
                    parsed_time.minute,
                    tzinfo=tz,
                )
                delivery_field = field(
                    "requested_delivery_at",
                    combined.isoformat(),
                    "VALID",
                    [(span_start, span_end)],
                    qualifier=qualifier,
                    metadata={
                        "qualifier": qualifier,
                        "raw_expression": text[span_start:span_end],
                        "timezone": message.raw.business_timezone or "",
                        "local_time": combined.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
        else:
            qualifier = "DATE_ONLY"
            delivery_field = field(
                "requested_delivery_at",
                parsed_date.date_val.isoformat(),
                "VALID",
                [(span_start, span_end)],
                qualifier=qualifier,
                metadata={
                    "qualifier": qualifier,
                    "raw_expression": text[span_start:span_end],
                    "timezone": message.raw.business_timezone or "",
                },
            )
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
        for alias in product.aliases:
            for match in re.finditer(ALIAS_BOUNDARY_PRE + re.escape(alias) + ALIAS_BOUNDARY_POST, text, re.IGNORECASE):
                key = (match.start(), match.end(), product.sku, product.unit)
                if not any(key == entry[0] for entry in mentions):
                    mentions.append((key, product, match))
    mentions.sort(key=lambda entry: entry[0])
    fields.extend(field("sku", p.sku, "VALID", [m.span()]) for _, p, m in mentions)

    # -----------------------------------------------------------------------
    # 4. Quantity and Unit Association
    # -----------------------------------------------------------------------
    # Numbers that fall inside orders or delivery spans are excluded from quantity candidates
    non_quantity_spans = [o.span() for o in orders] + delivery_spans

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
