"""/separate 集成测试（异步模型：产物落盘 + Job 记录 + 多产物 URL）。"""
from __future__ import annotations

from tests.conftest import wait_for_job


def _create_and_set_default_mock_separator(client):
    p = client.post("/api/admin/providers", json={
        "kind": "separator",
        "name": "mock-sep",
        "class_name": "InMemoryMockSeparatorProvider",
        "config": {},
    }).json()
    client.post(f"/api/admin/providers/{p['id']}/set-default")
    return p


def test_separate_returns_urls_and_persists_job(client, mock_all_registered):
    _create_and_set_default_mock_separator(client)
    r = client.post(
        "/api/separate",
        files={"audio": ("song.wav", b"RIFFsong", "audio/wav")},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    final = wait_for_job(client, job_id)
    assert final["kind"] == "separate"
    assert final["status"] == "succeeded"
    assert final["provider_name"] == "mock-sep"
    assert "vocals" in final["output_extras"]
    assert "instrumental" in final["output_extras"]

    # 产物可下载
    v = client.get(f"/api/jobs/{job_id}/output", params={"key": "vocals"})
    assert v.status_code == 200
    assert v.content.startswith(b"RIFF")

    i = client.get(f"/api/jobs/{job_id}/output", params={"key": "instrumental"})
    assert i.status_code == 200
    assert i.content.startswith(b"RIFF")
