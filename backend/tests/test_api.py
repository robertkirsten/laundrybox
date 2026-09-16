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
        assert client.get("/api/v1/state").json()["feedback_recorded"]

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
