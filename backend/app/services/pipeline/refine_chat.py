"""Plan Mode refinement chat — cheap clarification before expensive re-run.

Uses the fast 8b model with minimal context (field names + 2 sample rows)
to understand what the user wants. When the user confirms, returns a clear
instruction string to pass to the existing refine_and_start() method.
"""

import json
import logging
import re
from typing import Any

from app.services.llm.router import LLMTask, complete_json

logger = logging.getLogger("refine_chat")

_PLAN_MODEL = "llama-3.1-8b-instant"

_PLAN_SYSTEM_PROMPT = """You are a data extraction assistant in PLAN MODE. You help users clarify what they want to change in their document extraction results BEFORE running the expensive re-extraction.

You do NOT execute changes. You understand, clarify, and summarize.

CONTEXT: The user has extracted data from documents and sees results in a table. They want to fix or improve something.

YOUR JOB:
1. Decide whether the request is IN SCOPE for extraction refinement
2. If in scope: understand what to change; if ambiguous, ask ONE specific clarifying question
3. Summarize the planned changes clearly
4. When you have enough clarity, set ready=true

IN SCOPE (set in_scope=true):
- Fix / rename / add / remove extraction fields
- Change formats, units, date rules, calculations for extracted values
- Filtering, flagging, or set-field rules on extracted rows (exclude unpaid, flag over X, mark overdue)
- Correcting how a field should be computed from the document

OUT OF SCOPE (set in_scope=false, ready=false, accumulated_instruction=""):
- Summarize / translate / rewrite the whole document
- General chat, coding help, or unrelated questions
- Asking the system to email, call APIs, or do non-extraction work
- Requests that ignore the extraction results entirely

When out of scope, briefly refuse and steer back to extraction fields (1–2 sentences). Do NOT invent an accumulated_instruction.

WHEN TO SET ready=true (do this aggressively, only if in_scope=true):
- User names a field AND gives a corrected value, rule, or calculation (e.g. "should be 2 years", "use July 2024 start date")
- User answers your clarifying question with any specific detail
- User says "yes", "correct", "that's right", "apply it", "do that"
- User repeats the same correction twice — stop asking and set ready=true
- NEVER ask the same question twice. If chat_history shows you already asked, set ready=true with your best interpretation

FIELD CORRECTION EXAMPLE:
User: "years of experience is wrong, should be ~2 years"
You: {"in_scope": true, "ready": false, "message": "Got it — years_of_experience looks off. What rule should we use to calculate it?", "planned_changes": ["Fix years_of_experience calculation"], "accumulated_instruction": ""}

User: "2 years — they've worked at BNY since July 2024"
You: {"in_scope": true, "ready": true, "message": "Ready to apply: recalculate years_of_experience by summing role durations. Click Apply to re-run.", "planned_changes": ["Recalculate years_of_experience by summing role durations"], "accumulated_instruction": "years_of_experience: sum the duration of every entry in work_experience, including internships. For each role, duration_years = (end_date - start_date) / 365.25, using today's date when end_date is Present. Add the role durations together; do not use the calendar span from earliest start to latest end, and do not use education dates. Return a decimal number rounded to 2 places."}

RULES:
- Keep responses under 3 sentences
- Reference actual field names and sample values from the context
- Accumulate changes across multiple messages — don't reset
- accumulated_instruction is appended verbatim to the extraction prompt used on the documents. Write it as a direct extraction rule addressed to the extractor
- accumulated_instruction must be self-contained (the extractor never sees the chat history), must state HOW to compute or normalize the field, and must NOT contain the user's specific answer, company names, or arithmetic from one document
- Never write meta-commentary in accumulated_instruction (no "update the pipeline", "the user said", "add reusable rules")

OUTPUT FORMAT (JSON):
If out of scope:
{"in_scope": false, "ready": false, "message": "brief refusal steering back to extraction", "planned_changes": [], "accumulated_instruction": ""}

If still clarifying:
{"in_scope": true, "ready": false, "message": "your response", "planned_changes": ["change 1", "change 2"], "accumulated_instruction": ""}

If ready to apply:
{"in_scope": true, "ready": true, "message": "Ready to apply: [summary]. Click Apply to re-run.", "planned_changes": ["change 1"], "accumulated_instruction": "field_name: general rule describing how to compute or normalize the value."}
"""

_CLARIFY_MARKERS = (
    "can you specify",
    "what should",
    "correct value",
    "which field",
    "could you clarify",
    "specify the",
    "what is the",
    "what rule",
)

_CONFIRM_MARKERS = (
    "yes",
    "yeah",
    "yep",
    "correct",
    "that's right",
    "thats right",
    "apply",
    "do it",
    "go ahead",
    "sounds good",
    "looks good",
)


def _last_assistant_message(chat_history: list[dict[str, str]]) -> str:
    for msg in reversed(chat_history):
        if msg.get("role") == "assistant":
            return str(msg.get("content", ""))
    return ""


def _user_answered_clarification(
    chat_history: list[dict[str, str]],
    latest_message: str,
) -> bool:
    last_assistant = _last_assistant_message(chat_history).lower()
    if not last_assistant:
        return False
    if not any(marker in last_assistant for marker in _CLARIFY_MARKERS) and "?" not in last_assistant:
        return False
    text = latest_message.strip()
    if len(text) < 6:
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in _CONFIRM_MARKERS):
        return True
    if re.search(r"\d", text):
        return True
    if any(word in lowered for word in ("year", "month", "since", "from", "should be", "must be")):
        return True
    return len(text.split()) >= 6


def _is_repeated_assistant_response(
    chat_history: list[dict[str, str]],
    new_message: str,
) -> bool:
    last_assistant = _last_assistant_message(chat_history).strip().lower()
    if not last_assistant:
        return False
    new_normalized = new_message.strip().lower()
    if not new_normalized:
        return False
    if new_normalized == last_assistant:
        return True
    # Same question rephrased — high overlap
    last_words = set(last_assistant.split())
    new_words = set(new_normalized.split())
    if len(last_words) < 4:
        return False
    overlap = len(last_words & new_words) / max(len(last_words), 1)
    return overlap >= 0.75


def _collect_user_context(
    chat_history: list[dict[str, str]],
    latest_message: str,
) -> str:
    parts = [
        str(msg.get("content", "")).strip()
        for msg in chat_history
        if msg.get("role") == "user" and str(msg.get("content", "")).strip()
    ]
    if latest_message.strip():
        parts.append(latest_message.strip())
    return " ".join(parts)


def _build_accumulated_instruction(
    chat_history: list[dict[str, str]],
    latest_message: str,
    planned_changes: list[str],
    field_names: list[str],
) -> str:
    user_context = _collect_user_context(chat_history, latest_message)
    changes = "; ".join(planned_changes) if planned_changes else user_context
    # Appended verbatim to the extraction prompt, so it must read as an
    # extraction rule rather than an instruction to edit the pipeline.
    return (
        f"Apply this correction when extracting: {changes}. "
        f"User's description of the correct behaviour: {user_context}. "
        "Follow the described method rather than copying any example value."
    )


def _normalize_plan_result(
    result: dict[str, Any],
    *,
    chat_history: list[dict[str, str]],
    latest_message: str,
    field_names: list[str],
) -> dict[str, Any]:
    message = str(
        result.get(
            "message",
            "I didn't understand that. Could you describe what field or value needs to change?",
        )
    )
    planned_changes = list(result.get("planned_changes") or [])
    # Default True for older model responses that omit the key.
    in_scope = bool(result.get("in_scope", True))
    if "in_scope" in result and result.get("in_scope") is False:
        in_scope = False
    ready = bool(result.get("ready", False))
    accumulated = str(result.get("accumulated_instruction") or "").strip()

    if not in_scope:
        refuse = message.strip() or (
            "I can only help refine extraction fields and rules for this run — "
            "try naming a field to fix or how it should be calculated."
        )
        return {
            "in_scope": False,
            "ready": False,
            "message": refuse,
            "planned_changes": [],
            "accumulated_instruction": "",
        }

    user_answered = _user_answered_clarification(chat_history, latest_message)
    repeated = _is_repeated_assistant_response(chat_history, message)

    if not ready and (user_answered or repeated):
        ready = True
        if not accumulated:
            accumulated = _build_accumulated_instruction(
                chat_history,
                latest_message,
                planned_changes,
                field_names,
            )
        if repeated:
            message = (
                "Ready to apply your corrections. Click Apply to re-run extraction "
                "with the updated rules."
            )
        elif not message.lower().startswith("ready to apply"):
            summary = ", ".join(planned_changes) if planned_changes else "your corrections"
            message = f"Ready to apply: {summary}. Click Apply to re-run."

    return {
        "in_scope": True,
        "ready": ready,
        "message": message,
        "planned_changes": planned_changes,
        "accumulated_instruction": accumulated,
    }


async def plan_refinement(
    message: str,
    chat_history: list[dict[str, str]],
    field_names: list[str],
    sample_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Cheap clarification turn. Uses 8b model with minimal context.

    Returns dict with: in_scope, ready, message, planned_changes, accumulated_instruction
    """

    user_prompt = json.dumps(
        {
            "fields_in_results": field_names,
            "sample_values": sample_rows[:2],
            "chat_history": chat_history,
            "latest_message": message,
        },
        indent=2,
        default=str,
    )

    result = await complete_json(
        _PLAN_SYSTEM_PROMPT,
        user_prompt,
        task=LLMTask.PLAN_MODE,
        model=_PLAN_MODEL,
    )

    return _normalize_plan_result(
        result,
        chat_history=chat_history,
        latest_message=message,
        field_names=field_names,
    )
