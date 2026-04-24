"""/admin/providers CRUD 集成测试。"""
from __future__ import annotations


def test_list_default_providers(client):
    r = client.get("/api/admin/providers")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 4
    assert {p["kind"] for p in data} == {"asr", "tts", "cloning", "separator"}


def test_list_filter_by_kind(client):
    r = client.get("/api/admin/providers", params={"kind": "asr"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["kind"] == "asr"


def test_create_unknown_class_rejected(client):
    r = client.post("/api/admin/providers", json={
        "kind": "asr",
        "name": "bad",
        "class_name": "NonExistentProvider",
        "config": {},
    })
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "PROVIDER_UNKNOWN"


def test_create_provider_success(client):
    r = client.post("/api/admin/providers", json={
        "kind": "asr",
        "name": "whisper-tiny",
        "class_name": "WhisperProvider",
        "config": {"model_path": "/tmp/tiny"},
    })
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "whisper-tiny"
    assert data["is_default"] is False


def test_invalid_name_pattern_rejected(client):
    r = client.post("/api/admin/providers", json={
        "kind": "asr",
        "name": "Has Space",
        "class_name": "WhisperProvider",
        "config": {},
    })
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_update_provider(client):
    pid = client.get("/api/admin/providers", params={"kind": "tts"}).json()[0]["id"]
    r = client.patch(f"/api/admin/providers/{pid}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_set_default_mutually_exclusive(client):
    created = client.post("/api/admin/providers", json={
        "kind": "asr",
        "name": "alt-asr",
        "class_name": "WhisperProvider",
        "config": {"model_path": "/x"},
    }).json()
    r = client.post(f"/api/admin/providers/{created['id']}/set-default")
    assert r.status_code == 200
    assert r.json()["is_default"] is True

    all_asr = client.get("/api/admin/providers", params={"kind": "asr"}).json()
    defaults = [p for p in all_asr if p["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "alt-asr"


def test_delete_provider(client):
    created = client.post("/api/admin/providers", json={
        "kind": "asr",
        "name": "temp-asr",
        "class_name": "WhisperProvider",
        "config": {"model_path": "/x"},
    }).json()
    r = client.delete(f"/api/admin/providers/{created['id']}")
    assert r.status_code == 204

    missing = client.patch(f"/api/admin/providers/{created['id']}", json={"enabled": True})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "PROVIDER_NOT_FOUND"


def test_test_endpoint_succeeds_for_loadable_provider(client, mock_asr_registered):
    """Mock Provider 的 load() 不依赖磁盘文件，探活应成功。"""
    created = client.post("/api/admin/providers", json={
        "kind": "asr", "name": "probe-mock",
        "class_name": "InMemoryMockAsrProvider", "config": {},
    }).json()
    r = client.post(f"/api/admin/providers/{created['id']}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "probe-mock"
    assert body["detail"] == "model loaded"


def test_list_classes_returns_schema(client):
    """GET /admin/providers/classes 返回所有 registry 类，含 config 字段声明。"""
    r = client.get("/api/admin/providers/classes")
    assert r.status_code == 200
    data = r.json()
    class_names = {c["class_name"] for c in data}
    assert {"WhisperProvider", "PiperProvider", "DemucsProvider"} <= class_names

    whisper = next(c for c in data if c["class_name"] == "WhisperProvider")
    assert whisper["kind"] == "asr"
    assert whisper["label"]
    field_keys = {f["key"] for f in whisper["fields"]}
    assert {"model_path", "compute_type", "device", "simplify_chinese"} == field_keys
    compute_type = next(f for f in whisper["fields"] if f["key"] == "compute_type")
    assert compute_type["type"] == "enum"
    assert compute_type["options"] == ["int8", "fp16", "fp32"]
    assert compute_type["default"] == "int8"


def test_list_classes_filter_by_kind(client):
    r = client.get("/api/admin/providers/classes", params={"kind": "separator"})
    assert r.status_code == 200
    data = r.json()
    assert all(c["kind"] == "separator" for c in data)
    assert any(c["class_name"] == "DemucsProvider" for c in data)


def test_test_endpoint_reports_failure_when_model_missing(client):
    """种子 Whisper Provider 未下载模型：真实 load() 抛错 → ok=False + detail 透传。"""
    pid = client.get("/api/admin/providers", params={"kind": "asr"}).json()[0]["id"]
    r = client.post(f"/api/admin/providers/{pid}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["provider"] == "whisper-medium-int8"
    assert body["detail"]  # 具体错误码/消息
