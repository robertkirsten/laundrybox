from __future__ import annotations

from fastapi.testclient import TestClient

from argus_backend.api import create_app
from argus_backend.config import Settings

EPC = "E28011052000773410000001"


def test_debug_cycle_api_and_idempotent_feedback(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        initial = client.get("/api/v1/state")
        assert initial.status_code == 200
        assert initial.json()["lifecycle"] == "unavailable"
        assert initial.json()["decision"] is None

        for _ in range(settings.removal_confirm_samples):
            response = client.post(
                "/api/v1/debug/reports",
                json={"message": {"v": 1, "t": 0, "raw": 0, "weight_g": 0.0, "tags": []}},
            )
            assert response.status_code == 200
        assert response.json()["lifecycle"] == "waiting"

        for timestamp in (100, 200):
            response = client.post(
                "/api/v1/debug/reports",
                json={
                    "message": {
                        "v": 1,
                        "t": timestamp,
                        "raw": 10,
                        "weight_g": 241.0,
                        "stable": True,
                        "tags": [{"epc": EPC, "rssi": 92}],
                    }
                },
            )
            assert response.status_code == 200

        body = response.json()
        assert body["lifecycle"] == "pass"
        assert body["decision"] == "PASS"
        assert body["scanned_count"] == 1
        cycle_id = body["cycle_id"]

        feedback = client.post(
            f"/api/v1/cycles/{cycle_id}/inspection",
            json={"category": "nothing_found"},
        )
        assert feedback.status_code == 201
        assert not feedback.json()["duplicate"]
        feedback_state = client.get("/api/v1/state").json()
        assert feedback_state["feedback_recorded"]
        assert feedback_state["feedback_category"] == "nothing_found"

        duplicate = client.post(
            f"/api/v1/cycles/{cycle_id}/inspection",
            json={"category": "nothing_found"},
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["duplicate"]

        conflict = client.post(
            f"/api/v1/cycles/{cycle_id}/inspection",
            json={"category": "keys"},
        )
        assert conflict.status_code == 409


def test_debug_ingest_is_hidden_when_disabled(settings: Settings) -> None:
    safe_settings = settings.model_copy(update={"enable_debug_ingest": False})
    with TestClient(create_app(safe_settings)) as client:
        response = client.post(
            "/api/v1/debug/reports",
            json={"message": {"v": 1, "t": 0, "raw": 0, "weight_g": 0.0, "tags": []}},
        )
        assert response.status_code == 404


NEW_EPC = "AABB00112233445566778899"


def _drive_to_new_garment(client) -> str:
    for _ in range(2):
        client.post(
            "/api/v1/debug/reports",
            json={"message": {"v": 1, "t": 0, "raw": 0, "weight_g": 0.0, "tags": []}},
        )
    for timestamp in (100, 200):
        response = client.post(
            "/api/v1/debug/reports",
            json={
                "message": {
                    "v": 1,
                    "t": timestamp,
                    "raw": 10,
                    "weight_g": 320.0,
                    "stable": True,
                    "tags": [{"epc": NEW_EPC, "rssi": 88}],
                }
            },
        )
    body = response.json()
    assert body["lifecycle"] == "new_garment"
    assert body["pending_epc"] == NEW_EPC
    assert body["measurement"]["measured_g"] == 320.0
    return body["cycle_id"]


def test_register_new_garment_endpoint_passes(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        cycle_id = _drive_to_new_garment(client)
        response = client.post(
            f"/api/v1/cycles/{cycle_id}/garment",
            json={"action": "register", "product_name": "Testkittel"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["lifecycle"] == "pass"
        assert body["decision"] == "PASS"
        assert body["garment"]["product_name"] == "Testkittel"
        assert body["garment"]["wearer_name"] == "Nicht zugeordnet"
        assert body["measurement"]["reference_g"] == 320.0
        assert body["scanned_count"] == 1


def test_dismiss_new_garment_endpoint_checks(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        cycle_id = _drive_to_new_garment(client)
        response = client.post(
            f"/api/v1/cycles/{cycle_id}/garment",
            json={"action": "dismiss"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["lifecycle"] == "check"
        assert body["decision"] == "CHECK"
        assert body["reason"] == "unknown_tag"


def test_register_garment_unknown_cycle_returns_404(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        _drive_to_new_garment(client)
        response = client.post(
            "/api/v1/cycles/not-the-active-cycle/garment",
            json={"action": "register"},
        )
        assert response.status_code == 404
