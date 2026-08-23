"""
Deterministic value normalization for extracted fields.

Used by transform.normalize (and shareable with validators). No LLM.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_CURRENCY_MAP = {
    "$": "USD",
    "usd": "USD",
    "us$": "USD",
    "€": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "₹": "INR",
    "inr": "INR",
    "rs": "INR",
    "rs.": "INR",
    "¥": "JPY",
    "jpy": "JPY",
    "c$": "CAD",
    "cad": "CAD",
    "a$": "AUD",
    "aud": "AUD",
    "chf": "CHF",
    "sgd": "SGD",
    "hkd": "HKD",
    "cny": "CNY",
    "rmb": "CNY",
}

_AMOUNT_KEYS = (
    "amount",
    "total",
    "price",
    "cost",
    "tax",
    "subtotal",
    "fee",
    "balance",
    "rent",
    "deposit",
    "value",
)
_PHONE_KEYS = ("phone", "mobile", "tel", "fax")
_CURRENCY_KEYS = ("currency", "curr")


def is_date_field(name: str) -> bool:
    return "date" in name.lower()


def is_amount_field(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in _AMOUNT_KEYS)


def is_currency_field(name: str) -> bool:
    lower = name.lower()
    return lower == "currency" or any(
        kw == lower or lower.endswith(f"_{kw}") or lower.startswith(f"{kw}_")
        for kw in _CURRENCY_KEYS
    )


def is_phone_field(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in _PHONE_KEYS)


def normalize_amount(value: Any) -> Any:
    """Strip currency symbols and separators → float, or null / unchanged."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return value

    s = value.strip()
    if not s:
        return None

    s = re.sub(r"[€£¥₹$]", "", s)
    s = re.sub(r"(?i)\b(usd|eur|gbp|inr|jpy|cad|aud|rs\.?)\b", "", s)
    s = s.strip()
    if not s:
        return None

    # Indian grouping: 1,50,000 or 12,34,567.89
    if re.fullmatch(r"\d{1,3}(,\d{2})+,\d{3}(\.\d+)?", s) or re.fullmatch(
        r"\d{1,2}(,\d{2})+,\d{3}(\.\d+)?", s
    ):
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return value

    # EU: 1.234,56
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)", s):
        try:
            return float(s.replace(".", "").replace(",", "."))
        except ValueError:
            return value

    cleaned = s.replace(" ", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return value


def normalize_date(value: Any) -> Any:
    """Best-effort → YYYY-MM-DD; leave unparseable values unchanged."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value

    s = value.strip()
    if not s:
        return None

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s

    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            datetime.strptime(s[:10], "%Y-%m-%d")
            return s[:10]
        except ValueError:
            pass

    for fmt in (
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%d.%m.%Y",
        "%Y/%m/%d",
        "%d/%m/%y",
        "%m/%d/%y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue

    m = re.match(
        r"(?i)^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+'?(\d{2,4})$",
        s,
    )
    if m:
        day, mon, year = m.group(1), m.group(2).lower(), m.group(3)
        month = _MONTHS.get(mon)
        if month:
            y = int(year)
            if y < 100:
                y += 2000
            try:
                return datetime(y, month, int(day)).date().isoformat()
            except ValueError:
                pass

    return value


def normalize_currency(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return None
    key = s.lower()
    if key in _CURRENCY_MAP:
        return _CURRENCY_MAP[key]
    upper = s.upper()
    if upper in set(_CURRENCY_MAP.values()):
        return upper
    if len(s) == 1 and s in _CURRENCY_MAP:
        return _CURRENCY_MAP[s]
    return value


def normalize_phone(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return None
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return value
    return f"+{digits}" if plus else digits


def normalize_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    s = value.strip()
    return None if s == "" else s


def normalize_field_value(
    field: str,
    value: Any,
    *,
    field_types: Optional[dict[str, str]] = None,
) -> Any:
    """
    Normalize one field value.

    field_types optional map: field -> 'date' | 'amount' | 'currency' | 'phone' | 'string'
    """
    kind = (field_types or {}).get(field)
    if kind is None:
        if is_date_field(field):
            kind = "date"
        elif is_currency_field(field):
            kind = "currency"
        elif is_phone_field(field):
            kind = "phone"
        elif is_amount_field(field):
            kind = "amount"
        else:
            kind = "string"

    if kind == "date":
        return normalize_date(value)
    if kind == "amount":
        return normalize_amount(value)
    if kind == "currency":
        return normalize_currency(value)
    if kind == "phone":
        return normalize_phone(value)
    return normalize_string(value)


def build_field_type_map(
    field_names: list[str],
    *,
    date_fields: Optional[list[str]] = None,
    amount_fields: Optional[list[str]] = None,
    currency_fields: Optional[list[str]] = None,
    phone_fields: Optional[list[str]] = None,
) -> dict[str, str]:
    """Merge explicit config lists with heuristics for remaining fields."""
    types: dict[str, str] = {}
    for f in date_fields or []:
        types[f] = "date"
    for f in amount_fields or []:
        types[f] = "amount"
    for f in currency_fields or []:
        types[f] = "currency"
    for f in phone_fields or []:
        types[f] = "phone"
    for name in field_names:
        if name in types or name in ("flags", "document_id", "filename"):
            continue
        if is_date_field(name):
            types[name] = "date"
        elif is_currency_field(name):
            types[name] = "currency"
        elif is_phone_field(name):
            types[name] = "phone"
        elif is_amount_field(name):
            types[name] = "amount"
        else:
            types[name] = "string"
    return types
