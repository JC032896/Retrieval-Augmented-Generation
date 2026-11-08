from fastapi.testclient import TestClient

from tests.fixtures import client

__all__ = ["client"]


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
