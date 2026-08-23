"""
Template planner — builds a deterministic pipeline from a PipelineTemplate.

Unlike the LLM planner, template runs use curated fields, extraction instructions,
rules, and output format from the template definition.
"""

import uuid
from typing import Optional

from app.models.domain.pipeline import PipelinePlan, PlannedStep
from app.models.domain.template import PipelineTemplate
from app.services.documents.upload_loader import UploadDocumentInfo, load_upload_documents


async def create_plan_from_template(
    template: PipelineTemplate,
    upload_id: str,
) -> PipelinePlan:
    """Build a pipeline plan from a template and upload batch."""
    documents = await load_upload_documents(upload_id)
    if not documents:
        raise ValueError(f"No documents found for upload {upload_id}")

    steps = _build_steps(template, documents)

    return PipelinePlan(
        pipeline_id=str(uuid.uuid4()),
        upload_id=upload_id,
        task_description=template.task_description,
        steps=steps,
        summary=f"Template pipeline: {template.name}",
    )


def _build_steps(
    template: PipelineTemplate,
    documents: list[UploadDocumentInfo],
) -> list[PlannedStep]:
    steps: list[PlannedStep] = []
    order = 1

    processor_step = _processor_step_for_documents(documents)
    if processor_step is not None:
        steps.append(
            PlannedStep(
                step_order=order,
                agent_type=processor_step,
                config={},
                reason="Extract text from uploaded documents",
            )
        )
        order += 1

    steps.append(
        PlannedStep(
            step_order=order,
            agent_type="transform.field_extractor",
            config={
                "fields": list(template.fields),
                "instructions": template.extraction_instructions,
            },
            reason="Extract template fields with domain-specific instructions",
        )
    )
    order += 1

    steps.append(
        PlannedStep(
            step_order=order,
            agent_type="transform.normalize",
            config={},
            reason="Normalize dates, amounts, and currency to canonical forms",
        )
    )
    order += 1

    if template.rules:
        steps.append(
            PlannedStep(
                step_order=order,
                agent_type="transform.rules",
                config={"rules": list(template.rules)},
                reason="Apply template validation and flag rules",
            )
        )
        order += 1

    steps.append(
        PlannedStep(
            step_order=order,
            agent_type="output.formatter",
            config={"output_format": template.output_format},
            reason=f"Format results as {template.output_format.upper()}",
        )
    )

    return steps


def _processor_step_for_documents(
    documents: list[UploadDocumentInfo],
) -> Optional[str]:
    """Pick OCR vs text extract, or skip when upload already has text."""
    if all(doc.has_text for doc in documents):
        return None

    image_types = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}
    needs_ocr = any(
        doc.file_type.lower() in image_types
        or doc.extraction_method == "tesseract"
        for doc in documents
    )
    if needs_ocr:
        return "processor.ocr"
    return "processor.text_extract"
