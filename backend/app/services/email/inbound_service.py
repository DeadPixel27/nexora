"""Inbound email processing — parse webhook, extract attachments, run workflow."""

import logging
import uuid
from typing import Any

from app.config import settings
from app.models.domain.email import InboundAddress, InboundAddressNotFoundError
from app.models.domain.upload import UploadRecord
from app.persistence.protocols import DataRepository, DocumentStorageRepository

logger = logging.getLogger("inbound")


class InboundEmailService:
    def __init__(
        self,
        repo: DataRepository,
        doc_store: DocumentStorageRepository,
    ) -> None:
        self._repo = repo
        self._doc_store = doc_store

    def create_inbound_address(
        self,
        user_id: str,
        workflow_id: str,
    ) -> InboundAddress:
        """Return existing address for this workflow, or mint a new one."""
        existing = self._repo.get_inbound_address_for_workflow(workflow_id)
        if existing is not None:
            return existing

        prefix = f"flow-{uuid.uuid4().hex[:8]}"
        address = InboundAddress(
            address_id=prefix,
            full_address=f"{prefix}@{settings.inbound_email_domain}",
            user_id=user_id,
            workflow_id=workflow_id,
        )
        self._repo.save_inbound_address(address)
        logger.info(
            "Created inbound address %s for workflow %s",
            address.full_address,
            workflow_id,
        )
        return address

    def list_addresses(self, user_id: str) -> list[InboundAddress]:
        return self._repo.list_inbound_addresses(user_id)

    def delete_address(self, address_id: str) -> None:
        self._repo.delete_inbound_address(address_id)

    def resolve_address(self, recipient: str) -> InboundAddress:
        """Look up which user/workflow an inbound address maps to."""
        address_id = recipient.split("@")[0]
        address = self._repo.get_inbound_address(address_id)
        if address is None:
            raise InboundAddressNotFoundError(
                f"No workflow mapped to {recipient}"
            )
        return address

    async def process_inbound(
        self,
        recipient: str,
        sender: str,
        attachments: list[dict[str, Any]],
    ) -> tuple[str, str, str, str]:
        """Process an inbound email — save attachments and return routing info.

        Returns: (upload_id, workflow_id, sender, owner_user_id)
        """
        address = self.resolve_address(recipient)

        if not attachments:
            logger.warning("Inbound has no attachments")
            raise ValueError("Email has no attachments to process")

        from app.services.usage.page_count import (
            assert_within_page_limit,
            count_pages_from_bytes,
        )

        # Fail closed before storage — same per-file page cap as HTTP upload.
        for att in attachments:
            name = att.get("filename") or "attachment"
            content = att.get("content") or b""
            pages = count_pages_from_bytes(name, content)
            assert_within_page_limit(name, pages)

        upload_id = str(uuid.uuid4())
        for att in attachments:
            await self._doc_store.save_document_bytes(
                upload_id=upload_id,
                filename=att["filename"],
                content=att["content"],
                content_type=att["content_type"],
            )

        self._repo.save_upload(
            UploadRecord(upload_id=upload_id, user_id=address.user_id)
        )

        logger.info(
            "Inbound email → workflow %s, upload %s, user %s, attachments=%d",
            address.workflow_id,
            upload_id,
            address.user_id,
            len(attachments),
        )
        return upload_id, address.workflow_id, sender, address.user_id
