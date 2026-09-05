"""Shared field scoring helpers for document accuracy packs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class FieldScore:
    field: str
    expected: Any
    actual: Any
    ok: bool
    note: str = ""


@dataclass
class DocResult:
    path: Path
    template_id: str
    text_method: str
    text_len: int
    scores: list[FieldScore] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(s.ok for s in self.scores)


def norm_vendor(s: Any) -> str:
    if s is None:
        return ""
    t = str(s).lower().strip()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def vendor_match(expected: Any, actual: Any, threshold: float = 0.72) -> tuple[bool, str]:
    e, a = norm_vendor(expected), norm_vendor(actual)
    if not e and not a:
        return True, ""
    if not e or not a:
        return False, f"expected {expected!r}, got {actual!r}"
    if e in a or a in e:
        return True, ""
    ratio = SequenceMatcher(None, e, a).ratio()
    ok = ratio >= threshold
    return ok, (f"similarity={ratio:.2f}" if not ok else "")


def parse_amount(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    s = re.sub(r"[^\d.\-]", "", s.replace(",", ""))
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def amount_match(expected: Any, actual: Any, rel_tol: float = 0.005) -> tuple[bool, str]:
    e, a = parse_amount(expected), parse_amount(actual)
    if e is None and a is None:
        return True, ""
    if e is None or a is None:
        return False, f"expected {expected!r}, got {actual!r}"
    if e == 0:
        ok = abs(a) < 0.01
    else:
        ok = abs(a - e) <= max(0.01, abs(e) * rel_tol)
    return ok, ("" if ok else f"expected {e}, got {a}")


def parse_date(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d-%m-%y",
        "%d/%m/%y",
        "%m/%d/%y",
    ):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # SROIE-style compact dates: 12-01-19
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$", s)
    if m:
        d, mo, y = m.groups()
        year = int(y)
        if year < 100:
            year += 2000 if year < 50 else 1900
        try:
            return datetime(year, int(mo), int(d)).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s[:10] if len(s) >= 10 else s


def date_match(expected: Any, actual: Any) -> tuple[bool, str]:
    e, a = parse_date(expected), parse_date(actual)
    if not e and not a:
        return True, ""
    ok = e == a
    return ok, ("" if ok else f"expected {expected!r}, got {actual!r}")


def exact_match(expected: Any, actual: Any) -> tuple[bool, str]:
    ok = str(expected).strip().lower() == str(actual).strip().lower()
    return ok, ("" if ok else f"expected {expected!r}, got {actual!r}")


def present_match(_expected: Any, actual: Any) -> tuple[bool, str]:
    ok = actual is not None and str(actual).strip() != ""
    return ok, ("" if ok else "missing")


def min_count_match(min_count: int, actual: Any) -> tuple[bool, str]:
    if not isinstance(actual, list):
        return False, f"expected list with >={min_count}, got {type(actual).__name__}"
    ok = len(actual) >= min_count
    return ok, ("" if ok else f"expected >={min_count} items, got {len(actual)}")


def score_fields(
    expected: dict[str, Any],
    actual: dict[str, Any],
    matchers: dict[str, Callable[[Any, Any], tuple[bool, str]]],
) -> list[FieldScore]:
    scores: list[FieldScore] = []
    for fname, matcher in matchers.items():
        exp = expected.get(fname)
        act = actual.get(fname)
        if fname == "transactions" and isinstance(exp, int):
            ok, note = min_count_match(exp, act)
            scores.append(FieldScore(field=fname, expected=f">={exp} rows", actual=len(act) if isinstance(act, list) else act, ok=ok, note=note))
            continue
        ok, note = matcher(exp, act)
        scores.append(FieldScore(field=fname, expected=exp, actual=act, ok=ok, note=note))
    return scores


def score_presence(field_names: tuple[str, ...], actual: dict[str, Any]) -> list[FieldScore]:
    return [
        FieldScore(
            field=fname,
            expected="(present)",
            actual=actual.get(fname),
            ok=actual.get(fname) is not None and str(actual.get(fname)).strip() != "",
            note="no GT",
        )
        for fname in field_names
    ]


def print_report(results: list[DocResult], title: str) -> None:
    scored = [r for r in results if r.scores and r.scores[0].note != "no GT"]
    informational = [r for r in results if r.scores and r.scores[0].note == "no GT"]
    failed = [r for r in results if not r.passed]

    print(f"\n=== {title} ===\n")
    for r in results:
        try:
            rel = r.path.name if not r.path.is_absolute() else r.path
            if "fixtures/documents" in str(r.path):
                rel = r.path.relative_to(
                    next(p for p in r.path.parents if p.name == "documents")
                )
        except ValueError:
            rel = r.path
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {rel}  (text: {r.text_method}, {r.text_len} chars)")
        if r.error:
            print(f"       ERROR: {r.error}")
        for s in r.scores:
            mark = "ok" if s.ok else "MISS"
            extra = f" — {s.note}" if s.note else ""
            print(f"       {mark:4} {s.field}: expected={s.expected!r} actual={s.actual!r}{extra}")
        print()

    if scored:
        total_checks = sum(len(r.scores) for r in scored)
        ok_checks = sum(1 for r in scored for s in r.scores if s.ok)
        docs_ok = sum(1 for r in scored if r.passed)
        print(
            f"Scored: {docs_ok}/{len(scored)} docs fully correct, "
            f"{ok_checks}/{total_checks} field checks ({100 * ok_checks / total_checks:.1f}%)"
        )

    if informational:
        print(f"\nNo ground truth ({len(informational)} docs) — key fields present:")
        for r in informational:
            present = sum(1 for s in r.scores if s.ok)
            print(f"  {r.path.name}: {present}/{len(r.scores)} fields")

    if failed:
        print("\n--- Failures summary ---")
        by_field: dict[str, int] = {}
        for r in failed:
            for s in r.scores:
                if not s.ok:
                    by_field[s.field] = by_field.get(s.field, 0) + 1
        for fname, count in sorted(by_field.items(), key=lambda x: -x[1]):
            print(f"  {fname}: {count} miss(es)")
