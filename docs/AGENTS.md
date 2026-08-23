# Nexora — Agent Roster & Expansion Plan

*Current agents, planned agents, and how to add new ones.*

---

## Current Agents (6)

| Agent | Type | What it does | Uses LLM? |
|-------|------|--------------|-----------|
| `processor.text_extract` | Processor | PDF → text via PyMuPDF | No |
| `processor.ocr` | Processor | Image/scanned PDF → text via Tesseract | No |
| `transform.field_extractor` | Transform | Text → structured fields via Groq LLM | **Yes** |
| `transform.normalize` | Transform | Deterministic dates/amounts/currency/phones cleanup | No |
| `transform.rules` | Transform | Flag / filter / set on rows (gt, contains, exists, …) | No |
| `output.formatter` | Output | Rows → CSV or JSON | No |

**These cover most document extraction use cases. Enough for launch.**

---

## Post-Launch Agents — Priority Order

### Tier 1: Add Within 2 Weeks of Launch

| Agent | What it does | Why it's unique | Effort |
|-------|--------------|-----------------|--------|
| **`transform.classifier`** | Auto-classify document type (invoice vs receipt vs contract) | Smart routing — user uploads mixed docs, system sorts into right template | Low — one LLM call |
| **`transform.summarizer`** | Plain-English summary of each document | "This is a 2-year NDA between X and Y with auto-renewal" — 10x better results page | Low — one LLM call |
| **`output.excel`** | Output as formatted .xlsx with headers, widths, sheets | Accountants live in Excel. CSV is a compromise. .xlsx with formatting is a paid feature. | Low — openpyxl |

### Tier 2: Add Within Month 2

| Agent | What it does | Why |
|-------|--------------|-----|
| **`transform.translator`** | Translate extracted text/fields to another language | Opens non-English markets. Multilingual invoices are a real pain point. |
| **`transform.deduplicator`** | Flag or merge duplicate rows across documents | Accountants processing 100 invoices often have duplicates. |
| **`transform.calculator`** | Compute derived fields (totals, percentages, differences) | "Add tax_percentage = tax / subtotal" — tracked in [NEXT-STEPS.md](./NEXT-STEPS.md); ship after normalize/rules |


### Tier 3: Add When Users Ask

| Agent | What it does | Why |
|-------|--------------|-----|
| **`processor.table_extract`** | Detect and extract tables from PDFs (not just text) | Complex table PDFs are where all extractors struggle. |
| **`transform.validator`** | Cross-reference extracted data against external data | "Check if this vendor exists in my approved vendor list" |
| **`output.api_push`** | POST results to a webhook URL | For users integrating with their own systems |

---

## Adding a New Agent — 15 Minutes

The registry pattern makes it trivial:

```python
# backend/app/agents/handlers/transforms/summarizer.py

class SummarizerHandler(StepHandler):
    async def execute(self, ctx, config):
        documents = ctx.data.get("documents", [])
        summaries = []
        for doc in documents:
            summary = await complete_json(
                "Summarize this document in 2-3 sentences.",
                doc.get("text", ""),
            )
            summaries.append({
                "document_id": doc["document_id"],
                "filename": doc.get("filename", ""),
                "summary": summary.get("summary", ""),
            })
        ctx.data["summaries"] = summaries
        return StepResult(output={"documents_summarized": len(summaries)})

register_agent(
    "transform.summarizer",
    name="Summarizer",
    description="Generate plain-English summary of each document.",
    example_config={"max_length": 200},
    handler=SummarizerHandler(),
)
```

Planner automatically discovers it. Runner automatically executes it. No other code changes needed.

---

## New Agent Checklist

1. **Create file in correct subfolder:**
   - `handlers/processors/` — for text/OCR/input processing
   - `handlers/transforms/` — for LLM extraction, rules, calculations
   - `handlers/output/` — for formatting and delivery
2. **Subclass `StepHandler`, implement `async execute()`.**
3. **Call `register_agent()` at module level with:**
   - `agent_type` — namespaced: `category.name` (e.g., `transform.summarizer`)
   - `name` — human-readable
   - `description` — what the planner reads to decide when to use it
   - `example_config` — planner uses this to generate correct config
   - `handler` — instance of your `StepHandler` subclass
4. **Import the new module in `handlers/__init__.py`.**
5. **Write a test in `tests/test_{agent_name}_agent.py`.**

---

*Registry pattern — no `if agent == "ocr"` in runner.*
