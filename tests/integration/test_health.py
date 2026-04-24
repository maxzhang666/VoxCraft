from fastapi.testclient import TestClient

from voxcraft.main import app


def test_health_returns_ok():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["db"] is True
    assert "gpu" in data
