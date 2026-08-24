from typing import Optional

from pydantic import BaseModel


class IntegrationsStatusResponse(BaseModel):
    """Public integration setup hints for the UI walkthrough."""

    email_configured: bool = False
    sheets_configured: bool = False
    sheets_share_email: Optional[str] = None
    inbound_email_domain: str = ""
    inbound_configured: bool = False
