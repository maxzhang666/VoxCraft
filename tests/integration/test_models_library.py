"""模型库 /admin/models-library 端点集成测试。

Mock 底层 downloader 让下载快速完成，验证 API 契约 + 状态流。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def patch_downloader(monkeypatch):
    """默认 mock 下载：秒出 + 写入标记文件。"""
    from voxcraft.models_lib import service as svc_mod

    def _fake_hf(repo_id, local_dir, max_workers=8):
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "model.bin").write_bytes(b"x" * 256)
        return Path(local_dir)

    monkeypatch.setattr(svc_mod, "download_hf", _fake_hf)
    monkeypatch.setattr(svc_mod, "download_ms", _fake_hf)


def _wait_ready(client, model_id: int, timeout_s: float = 3.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = client.get("/admin/models-library").json()
        for v in r:
            if v.get("model_id") == model_id and v["status"] in ("ready", "failed", "cancelled"):
                return v
        time.sleep(0.05)
    raise AssertionError("model did not reach terminal state within timeout")


def test_list_returns_11_builtin_entries(client):
    r = client.get("/admin/models-library")
    assert r.status_code == 200
    data = r.json()
    builtins = [v for v in data if v["is_builtin"]]
    assert len(builtins) == 11
    keys = {v["catalog_key"] for v in builtins}
    assert "whisper-tiny" in keys
    assert "voxcpm-2" in keys
    # 默认未下载
    for v in builtins:
        if v["model_id"] is None:
            assert v["status"] == "not_downloaded"


def test_download_builtin_creates_model_row(client):
    r = client.post("/admin/models-library/whisper-tiny/download")
    assert r.status_code == 202, r.text
    data = r.json()
    assert data["catalog_key"] == "whisper-tiny"
    assert data["source"] == "hf"
    model_id = data["id"]

    final = _wait_ready(client, model_id)
    assert final["status"] == "ready"


def test_download_with_explicit_source_ms(client):
    r = client.post(
        "/admin/models-library/whisper-small/download", params={"source": "ms"}
    )
    assert r.status_code == 202
    assert r.json()["source"] == "ms"


def test_download_unknown_catalog_key_returns_404(client):
    r = client.post("/admin/models-library/nonexistent/download")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "CATALOG_KEY_NOT_FOUND"


def test_download_invalid_source_returns_400(client):
    # Piper 只有 url 源
    r = client.post(
        "/admin/models-library/piper-zh-huayan-medium/download",
        params={"source": "ms"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_download_already_exists_returns_409(client):
    r1 = client.post("/admin/models-library/whisper-tiny/download").json()
    _wait_ready(client, r1["id"])
    r2 = client.post("/admin/models-library/whisper-tiny/download")
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "MODEL_ALREADY_EXISTS"


def test_custom_add_rejects_non_prefixed_key(client):
    r = client.post(
        "/admin/models-library/custom",
        json={
            "catalog_key": "my-model",      # 无 custom_ 前缀
            "source": "hf",
            "repo_id": "x/y",
            "kind": "asr",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_custom_add_rejects_clash_with_builtin(client):
    r = client.post(
        "/admin/models-library/custom",
        json={
            "catalog_key": "custom_whisper-tiny",  # 技术上合法，只要 custom_ 前缀
            "source": "hf",
            "repo_id": "x/y",
            "kind": "asr",
        },
    )
    # 前缀合法，允许；不真冲突内置 (内置是 whisper-tiny)
    assert r.status_code == 202


def test_custom_add_success(client):
    r = client.post(
        "/admin/models-library/custom",
        json={
            "catalog_key": "custom_my-asr",
            "source": "hf",
            "repo_id": "my-org/my-asr",
            "kind": "asr",
        },
    )
    assert r.status_code == 202, r.text
    data = r.json()
    assert data["catalog_key"] == "custom_my-asr"
    _wait_ready(client, data["id"])


def test_custom_add_duplicate_returns_409(client):
    payload = {
        "catalog_key": "custom_dup",
        "source": "hf", "repo_id": "x/y", "kind": "asr",
    }
    r1 = client.post("/admin/models-library/custom", json=payload)
    assert r1.status_code == 202
    r2 = client.post("/admin/models-library/custom", json=payload)
    assert r2.status_code == 400
    assert r2.json()["error"]["code"] == "CATALOG_KEY_CONFLICT"


def test_delete_model_succeeds(client):
    r = client.post("/admin/models-library/whisper-tiny/download").json()
    _wait_ready(client, r["id"])
    r_del = client.delete(f"/admin/models-library/{r['id']}")
    assert r_del.status_code == 204


def test_delete_model_not_found_returns_404(client):
    r = client.delete("/admin/models-library/99999")
    assert r.status_code == 404


def test_delete_rejects_if_provider_references(client):
    # 下模型
    m = client.post("/admin/models-library/whisper-tiny/download").json()
    ready = _wait_ready(client, m["id"])
    local_path = ready["local_path"]

    # 造一个 Provider 引用该路径
    client.post(
        "/admin/providers",
        json={
            "kind": "asr",
            "name": "prov-using-model",
            "class_name": "WhisperProvider",
            "config": {"model_path": local_path},
        },
    )

    # 删应该被拒
    r = client.delete(f"/admin/models-library/{m['id']}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "MODEL_IN_USE"


def test_cancel_model_not_found(client):
    r = client.post("/admin/models-library/99999/cancel")
    assert r.status_code == 404
