"""/admin/llm CRUD 集成测试（v0.3.0）。"""
from __future__ import annotations


def _create(client, **overrides) -> dict:
    body = {
        "name": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test-1234",
        "model": "gpt-4o-mini",
        **overrides,
    }
    r = client.post("/api/admin/llm", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_llm_crud_roundtrip(client):
    created = _create(client)
    assert created["name"] == "openai"
    # api_key 不得出现在响应中
    assert "api_key" not in created

    lst = client.get("/api/admin/llm").json()
    assert len(lst) == 1
    assert "api_key" not in lst[0]


def test_llm_patch_empty_api_key_preserves_original(client):
    created = _create(client, api_key="sk-original")
    id_ = created["id"]

    # PATCH 留空 api_key → 不应覆盖原值
    r = client.patch(f"/api/admin/llm/{id_}", json={"api_key": "", "model": "gpt-4o"})
    assert r.status_code == 200
    assert r.json()["model"] == "gpt-4o"

    # 从 DB 直接验证原 api_key 仍在
    from voxcraft.db.engine import get_engine
    from voxcraft.db.models import LlmProvider
    from sqlmodel import Session
    with Session(get_engine()) as s:
        row = s.get(LlmProvider, id_)
        assert row.api_key == "sk-original"


def test_llm_patch_new_api_key_overrides(client):
    created = _create(client, api_key="sk-old")
    id_ = created["id"]
    client.patch(f"/api/admin/llm/{id_}", json={"api_key": "sk-new"})

    from voxcraft.db.engine import get_engine
    from voxcraft.db.models import LlmProvider
    from sqlmodel import Session
    with Session(get_engine()) as s:
        row = s.get(LlmProvider, id_)
        assert row.api_key == "sk-new"


def test_llm_set_default_is_mutually_exclusive(client):
    a = _create(client, name="a", is_default=True)
    b = _create(client, name="b", is_default=False)
    r = client.post(f"/api/admin/llm/{b['id']}/set-default")
    assert r.status_code == 200
    assert r.json()["is_default"] is True

    refreshed_a = next(x for x in client.get("/api/admin/llm").json() if x["id"] == a["id"])
    assert refreshed_a["is_default"] is False


def test_llm_delete(client):
    created = _create(client)
    r = client.delete(f"/api/admin/llm/{created['id']}")
    assert r.status_code == 204
    assert client.get("/api/admin/llm").json() == []


def test_llm_not_found_errors(client):
    r = client.get("/api/admin/llm")
    assert r.json() == []
    r2 = client.patch("/api/admin/llm/999", json={"model": "x"})
    assert r2.status_code == 404
    assert r2.json()["error"]["code"] == "LLM_PROVIDER_NOT_FOUND"


def test_probe_models_with_explicit_api_key(client, monkeypatch):
    """新建场景：api_key + base_url 调 probe-models。"""
    _patch_openai_models(monkeypatch, ids=["gpt-4o", "gpt-4o-mini"])
    r = client.post(
        "/api/admin/llm/probe-models",
        json={"base_url": "https://api.openai.com/v1", "api_key": "sk-new"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"models": ["gpt-4o", "gpt-4o-mini"]}


def test_probe_models_with_use_id(client, monkeypatch):
    """编辑场景：不暴露 api_key，只传 use_id。"""
    created = _create(client, api_key="sk-stored")
    _patch_openai_models(monkeypatch, ids=["deepseek-chat"])

    r = client.post(
        "/api/admin/llm/probe-models",
        json={"base_url": "https://api.deepseek.com/v1", "use_id": created["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["models"] == ["deepseek-chat"]


def test_probe_models_use_id_not_found(client):
    r = client.post(
        "/api/admin/llm/probe-models",
        json={"base_url": "https://x", "use_id": 99999},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "LLM_PROVIDER_NOT_FOUND"


def test_probe_models_requires_auth(client):
    # 既无 api_key 也无 use_id
    r = client.post("/api/admin/llm/probe-models", json={"base_url": "https://x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_probe_models_upstream_failure(client, monkeypatch):
    _patch_openai_models(
        monkeypatch, raise_exc=RuntimeError("401 Unauthorized"),
    )
    r = client.post(
        "/api/admin/llm/probe-models",
        json={"base_url": "https://x", "api_key": "sk-bad"},
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "LLM_API_ERROR"


# ---------- helper：mock httpx.get（list_models 已改走 httpx 直调） ----------

def _patch_openai_models(monkeypatch, *, ids=None, raise_exc=None):
    import httpx

    def fake_get(url, headers=None, timeout=None):  # noqa: ARG001
        if raise_exc is not None:
            raise raise_exc
        return httpx.Response(
            200,
            json={"data": [{"id": i} for i in (ids or [])]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)


def test_llm_name_validation(client):
    r = client.post("/api/admin/llm", json={
        "name": "Has Space",
        "base_url": "https://x", "api_key": "sk", "model": "m",
    })
    # 项目统一 error_handlers 把 Pydantic 422 转成 400 envelope
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
