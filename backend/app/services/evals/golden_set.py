"""Golden-set fixtures for the interview-signal eval harness.

Keep the default suite ≤10 docs so admin runs stay inline (no job queue).
Larger packs remain in scripts/run_document_accuracy_pack.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from app.services.evals.scoring import amount_match, date_match, vendor_match

BACKEND = Path(__file__).resolve().parents[3]
FIX = BACKEND / "tests" / "fixtures" / "documents"

Matcher = Callable[[Any, Any], tuple[bool, str]]


@dataclass(frozen=True)
class GoldenCase:
    relative_path: str
    template_id: str
    expected: dict[str, Any]
    matchers: dict[str, Matcher]


def _load_invoice_gt(stem: str) -> Optional[dict[str, Any]]:
    gt_path = FIX / "invoices" / "invoicebenchmark_ground_truth" / f"{stem}.json"
    if not gt_path.exists():
        return None
    with open(gt_path) as f:
        gt = json.load(f)
    return {
        "vendor_name": gt.get("vendor"),
        "invoice_date": gt.get("date"),
        "total_amount": gt.get("total"),
    }


INVOICE_MATCHERS: dict[str, Matcher] = {
    "vendor_name": vendor_match,
    "invoice_date": date_match,
    "total_amount": amount_match,
}

RECEIPT_MATCHERS: dict[str, Matcher] = {
    "merchant_name": vendor_match,
    "receipt_date": date_match,
    "total_amount": amount_match,
}


def default_golden_cases() -> list[GoldenCase]:
    """Small scored suite with ground truth (inline admin-safe size)."""
    cases: list[GoldenCase] = []

    for stem in ("INV-2026-0001", "INV-2026-0002", "INV-2026-0003"):
        expected = _load_invoice_gt(stem)
        pdf = FIX / "invoices" / "invoicebenchmark" / f"{stem}.pdf"
        if expected and pdf.exists():
            cases.append(
                GoldenCase(
                    relative_path=f"invoices/invoicebenchmark/{stem}.pdf",
                    template_id="invoice",
                    expected=expected,
                    matchers=INVOICE_MATCHERS,
                )
            )

    gst = [
        (
            "invoices/gst/gst-intra-cgst-sgst.pdf",
            {
                "vendor_name": "Acme Supplies Pvt Ltd",
                "invoice_date": "2026-01-15",
                "total_amount": 17700.0,
            },
        ),
        (
            "invoices/gst/gst-inter-igst.pdf",
            {
                "vendor_name": "Acme Supplies Pvt Ltd",
                "invoice_date": "2026-01-20",
                "total_amount": 20650.0,
            },
        ),
    ]
    for rel, expected in gst:
        if (FIX / rel).exists():
            cases.append(
                GoldenCase(
                    relative_path=rel,
                    template_id="invoice",
                    expected=expected,
                    matchers=INVOICE_MATCHERS,
                )
            )

    sroie_gt = FIX / "receipts" / "sroie_ground_truth"
    for stem in ("sroie-000", "sroie-001", "sroie-002"):
        jpg = FIX / "receipts" / "sroie" / f"{stem}.jpg"
        gt_path = sroie_gt / f"{stem}.json"
        if not jpg.exists() or not gt_path.exists():
            continue
        with open(gt_path) as f:
            ent = json.load(f).get("entities", {})
        cases.append(
            GoldenCase(
                relative_path=f"receipts/sroie/{stem}.jpg",
                template_id="receipt",
                expected={
                    "merchant_name": ent.get("company"),
                    "receipt_date": ent.get("date"),
                    "total_amount": ent.get("total"),
                },
                matchers=RECEIPT_MATCHERS,
            )
        )

    novus = FIX / "receipts" / "novus-receipt.pdf"
    if novus.exists():
        cases.append(
            GoldenCase(
                relative_path="receipts/novus-receipt.pdf",
                template_id="receipt",
                expected={
                    "merchant_name": "Meridian Supply Co.",
                    "receipt_date": "2026-01-20",
                    "total_amount": 773.61,
                },
                matchers=RECEIPT_MATCHERS,
            )
        )

    return cases


def resolve_cases(
    *,
    template_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[GoldenCase]:
    cases = default_golden_cases()
    if template_id and template_id != "all":
        cases = [c for c in cases if c.template_id == template_id]
    if limit is not None and limit > 0:
        cases = cases[:limit]
    return cases


def fixture_path(relative_path: str) -> Path:
    return FIX / relative_path
