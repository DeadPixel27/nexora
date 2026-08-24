"""Public /api/integrations setup hints."""

import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_integrations_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "")
    monkeypatch.setattr(settings, "google_service_account_json", "")
    monkeypatch.setattr(settings, "inbound_email_domain", "ingest.example.com")
    monkeypatch.setattr(settings, "inbound_webhook_secret", "")

    response = client.get("/api/integrations")
    assert response.status_code == 200
    body = response.json()
    assert body["email_configured"] is False
    assert body["sheets_configured"] is False
    assert body["sheets_share_email"] is None
    assert body["inbound_email_domain"] == "ingest.example.com"
    assert body["inbound_configured"] is False


def test_integrations_inbound_configured(monkeypatch):
    monkeypatch.setattr(settings, "inbound_webhook_secret", "mg-signing-key")
    monkeypatch.setattr(settings, "inbound_email_domain", "ingest.example.com")

    response = client.get("/api/integrations")
    assert response.status_code == 200
    body = response.json()
    assert body["inbound_configured"] is True
    assert body["inbound_email_domain"] == "ingest.example.com"


def test_integrations_exposes_sheets_share_email(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(
        settings,
        "google_service_account_json",
        json.dumps(
            {
                "type": "service_account",
                "client_email": "nexora@project.iam.gserviceaccount.com",
                "token_uri": "https://oauth2.googleapis.com/token",
                "private_key": "-----BEGIN PRIVATE KEY-----\nX\n-----END PRIVATE KEY-----\n",
            }
        ),
    )

    response = client.get("/api/integrations")
    assert response.status_code == 200
    body = response.json()
    assert body["email_configured"] is True
    assert body["sheets_configured"] is True
    assert (
        body["sheets_share_email"]
        == "nexora@project.iam.gserviceaccount.com"
    )
