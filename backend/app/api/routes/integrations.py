"""Public integration status — setup hints for email / Sheets / inbound UI."""

from fastapi import APIRouter

from app.config import settings
from app.models.api.integrations import IntegrationsStatusResponse
from app.services.sheets.sheets_service import get_sheets_share_email

router = APIRouter(tags=["integrations"])


@router.get("/api/integrations", response_model=IntegrationsStatusResponse)
async def integrations_status() -> IntegrationsStatusResponse:
    share_email = get_sheets_share_email()
    return IntegrationsStatusResponse(
        email_configured=bool(settings.resend_api_key.strip()),
        sheets_configured=bool(share_email),
        sheets_share_email=share_email,
        inbound_email_domain=settings.inbound_email_domain,
        inbound_configured=bool(settings.inbound_webhook_secret.strip()),
    )
