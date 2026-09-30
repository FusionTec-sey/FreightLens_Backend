import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test"
)

from fastapi import FastAPI
from fastapi.testclient import TestClient

import LogisticsAPI.router as router_module


def _client(monkeypatch, configured_secret="carrier-test-secret"):
    monkeypatch.setattr(
        router_module.settings, "CMA_CGM_WEBHOOK_SECRET", configured_secret
    )
    app = FastAPI()
    app.include_router(router_module.logistics_webhook_router)
    return TestClient(app)


def test_webhook_rejects_missing_secret(monkeypatch):
    response = _client(monkeypatch).post(
        "/api/logistics/webhook/cma-cgm", json={"eventType": "EQUIPMENT"}
    )
    assert response.status_code == 401


def test_webhook_rejects_invalid_secret(monkeypatch):
    response = _client(monkeypatch).post(
        "/api/logistics/webhook/cma-cgm",
        headers={"X-Webhook-Secret": "wrong"},
        json={"eventType": "EQUIPMENT"},
    )
    assert response.status_code == 401


def test_webhook_fails_closed_when_secret_is_not_configured(monkeypatch):
    response = _client(monkeypatch, configured_secret="").post(
        "/api/logistics/webhook/cma-cgm",
        headers={"X-Webhook-Secret": "anything"},
        json={"eventType": "EQUIPMENT"},
    )
    assert response.status_code == 503


def test_webhook_processes_authenticated_json_object(monkeypatch):
    received = {}

    def process(raw_payload):
        received.update(raw_payload)
        return {"status": "success"}

    monkeypatch.setattr(router_module._webhook_service, "process_cma_webhook", process)
    response = _client(monkeypatch).post(
        "/api/logistics/webhook/cma-cgm",
        headers={"X-Webhook-Secret": "carrier-test-secret"},
        json={"eventType": "EQUIPMENT", "equipmentReference": "MSCU1234567"},
    )
    assert response.status_code == 200
    assert received["equipmentReference"] == "MSCU1234567"


def test_webhook_rejects_non_object_payload(monkeypatch):
    response = _client(monkeypatch).post(
        "/api/logistics/webhook/cma-cgm",
        headers={"X-Webhook-Secret": "carrier-test-secret"},
        json=[{"eventType": "EQUIPMENT"}],
    )
    assert response.status_code == 400
