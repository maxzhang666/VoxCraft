from fastapi.testclient import TestClient

from voxcraft.main import app


def test_health_returns_ok():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["db"] is True
    # gpu 改为对象：不假设 CI/mac 上是否有 GPU，仅校验结构与字段类型
    gpu = data["gpu"]
    assert isinstance(gpu, dict)
    assert isinstance(gpu["available"], bool)
    assert isinstance(gpu["used_mb"], int)
    assert isinstance(gpu["total_mb"], int)
    assert gpu["name"] is None or isinstance(gpu["name"], str)
