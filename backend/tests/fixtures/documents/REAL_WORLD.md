# Getting real-world documents (legal + practical)

## What “real world” means here

| Tier | Examples | Good for |
|------|----------|----------|
| **Public research datasets** | SROIE receipts, InvoiceBenchmark, Bankstatemently | OCR + field benchmarks (already in repo) |
| **Synthetic-but-realistic** | GST PDFs, Indian bank HF, rasterized JPGs | Pipeline regression without PII |
| **Your own / beta user docs** | Redacted vendor invoices | **Best** pre-launch accuracy signal |

We **cannot** legally scrape random invoices from Google, use employer (BNY) docs, or download strangers’ PDFs.

---

## Already in this repo (public / licensed)

| Source | Folder | Real? |
|--------|--------|-------|
| SROIE (CC-BY-4.0) | `receipts/sroie/` | **Yes** — real scanned receipts |
| InvoiceBenchmark | `invoices/invoicebenchmark/` + `ocr/invoicebenchmark/` | Synthetic with perfect labels |
| Bankstatemently (open benchmark) | `bank_statements/bankstatemently/` | Synthetic bank layouts (real parsing challenges) |
| Indian bank statements (HF, Apache) | `bank_statements/indian_synthetic/` | Synthetic India UPI/NEFT-style |
| Azure / Novus / PDFCrowd | `invoices/`, `receipts/` | Demo / fixture PDFs |

---

## What you should collect yourself (best ROI)

1. **Ask 3–5 people** who do AP weekly (friend, bookkeeper, SMB owner).
2. **They send 2–3 invoices/receipts each** — with vendor names redacted if they want.
3. Save under `tests/fixtures/documents/private/` — **gitignored**, never commit.
4. Run Nexora, note failures, fix invoice template first.

Add to `.gitignore` (if you create the folder):

```
backend/tests/fixtures/documents/private/
```

---

## Larger public datasets (manual download)

These are **real scanned invoices** but require you to register or download manually:

| Dataset | Size | License | How |
|---------|------|---------|-----|
| **MIDD** (630 scanned invoice PDFs, India layouts) | ~630 PDF | CC-BY-4.0 | [MDPI supplementary](https://www.mdpi.com/article/10.3390/data6070078/s1) — browser download |
| **INV-CDIP** (350 labeled invoices) | 350 | CC-BY-NC-4.0 | [GitHub](https://github.com/salesforce/inv-cdip) — non-commercial |
| **Innovatiana OCR invoices** | ~1560 image+XML | CC0 | [Innovatiana](https://www.innovatiana.com/en/datasets/text-extraction-for-ocr) |

After download, copy a **20–30 file sample** into `invoices/midd/` or similar — don’t commit full 630 unless you need them.

---

## What we will not do

- Scrape IDP / document-AI competitors’ customer uploads
- Use BNY / employer documents
- Commit PII (GSTIN, account numbers from real people) to git

Synthetic fixtures use fake GSTINs and account numbers only.
