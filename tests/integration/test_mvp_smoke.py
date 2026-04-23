"""MVP v0.1 端到端 Smoke：按真实用户流程串起所有主路径（异步模型）。"""
from __future__ import annotations

from tests.conftest import wait_for_job


def _create_mock_set(client):
    """注入 4 个 Mock Provider 作为默认，覆盖 ASR/TTS/Cloning/Separator。"""
    specs = [
        ("asr", "mock-asr", "InMemoryMockAsrProvider"),
        ("tts", "mock-tts", "InMemoryMockTtsProvider"),
        ("cloning", "mock-clone", "InMemoryMockCloningProvider"),
        ("separator", "mock-sep", "InMemoryMockSeparatorProvider"),
    ]
    ids: dict[str, int] = {}
    for kind, name, cls in specs:
        r = client.post(
            "/admin/providers",
            json={"kind": kind, "name": name, "class_name": cls, "config": {}},
        )
        assert r.status_code == 201, r.text
        ids[kind] = r.json()["id"]
        assert client.post(f"/admin/providers/{ids[kind]}/set-default").status_code == 200
    return ids


def test_mvp_smoke_full_flow(client, mock_all_registered):
    """一次性覆盖：Provider CRUD → 业务调用 → Job 写入 → 产物下载 → 删除 → 健康检查。"""
    # 1. 健康
    assert client.get("/health").status_code == 200

    # 2. 初始种子 4 条
    seed = client.get("/admin/providers").json()
    assert len(seed) == 4

    # 3. 注入 Mock + 设默认（覆盖种子）
    _create_mock_set(client)

    # 4. /asr（异步：202 + job_id，轮询至 succeeded）
    r_asr = client.post(
        "/asr",
        files={"audio": ("a.wav", b"RIFFfake", "audio/wav")},
        data={"language": "zh"},
    )
    assert r_asr.status_code == 202, r_asr.text
    asr_job_id = r_asr.json()["job_id"]
    asr_final = wait_for_job(client, asr_job_id)
    assert asr_final["status"] == "succeeded"
    assert asr_final["provider_name"] == "mock-asr"

    # 5. /tts
    r_tts = client.post("/tts", json={"text": "你好", "voice_id": "mock-voice"})
    assert r_tts.status_code == 202, r_tts.text
    tts_job_id = r_tts.json()["job_id"]
    assert wait_for_job(client, tts_job_id)["status"] == "succeeded"

    # 6. /tts/clone
    r_clone = client.post(
        "/tts/clone",
        files={"reference_audio": ("ref.wav", b"RIFFref", "audio/wav")},
        data={"text": "克隆测试"},
    )
    assert r_clone.status_code == 202, r_clone.text
    clone_job_id = r_clone.json()["job_id"]
    clone_final = wait_for_job(client, clone_job_id)
    assert clone_final["status"] == "succeeded"
    voice_id = clone_final["request"]["voice_id"]

    # 7. /separate
    r_sep = client.post("/separate", files={"audio": ("s.wav", b"RIFFs", "audio/wav")})
    assert r_sep.status_code == 202, r_sep.text
    sep_job_id = r_sep.json()["job_id"]
    assert wait_for_job(client, sep_job_id)["status"] == "succeeded"

    # 8. 跨能力 Jobs 列表：4 条
    jobs = client.get("/jobs").json()
    assert len(jobs) == 4
    assert {j["kind"] for j in jobs} == {"asr", "tts", "clone", "separate"}

    # 9. 能力页过滤
    asr_jobs = client.get("/jobs", params={"kind": "asr"}).json()
    assert len(asr_jobs) == 1

    # 10. TTS / Clone 产物下载
    assert client.get(f"/jobs/{tts_job_id}/output").status_code == 200
    assert client.get(f"/jobs/{clone_job_id}/output").status_code == 200

    # 11. Separator 多产物
    assert client.get(f"/jobs/{sep_job_id}/output", params={"key": "vocals"}).status_code == 200
    assert client.get(f"/jobs/{sep_job_id}/output", params={"key": "instrumental"}).status_code == 200

    # 12. 预览流（无 attachment）
    r_preview = client.get(f"/jobs/{tts_job_id}/output/preview")
    assert r_preview.status_code == 200
    assert "attachment" not in r_preview.headers.get("content-disposition", "")

    # 13. 音色列表含新创建的 voice_id
    voices = client.get("/tts/voices").json()["voices"]
    assert any(v["id"] == voice_id for v in voices)

    # 14. /models 聚合视图
    models = client.get("/models").json()
    assert "mock-asr" in models["asr"]
    assert "mock-tts" in models["tts"]

    # 15. 删除 Job → 产物链同步失效
    assert client.delete(f"/jobs/{tts_job_id}").status_code == 204
    assert client.get(f"/jobs/{tts_job_id}").status_code == 404

    # 16. Jobs 列表按 status 过滤
    succeeded = client.get("/jobs", params={"status": "succeeded"}).json()
    assert all(j["status"] == "succeeded" for j in succeeded)


def test_mvp_smoke_error_paths(client, mock_all_registered):
    """错误路径：触发 VALIDATION_ERROR / PROVIDER_NOT_FOUND / JOB_OUTPUT_NOT_READY。"""
    # 1. 非法 Provider 名称
    r = client.post(
        "/admin/providers",
        json={"kind": "asr", "name": "Has Space", "class_name": "X", "config": {}},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    # 2. 未知 class_name
    r2 = client.post(
        "/admin/providers",
        json={"kind": "asr", "name": "x", "class_name": "Nope", "config": {}},
    )
    assert r2.status_code == 400
    assert r2.json()["error"]["code"] == "PROVIDER_UNKNOWN"

    # 3. Job 不存在
    r3 = client.get("/jobs/nonexistent")
    assert r3.status_code == 404
    assert r3.json()["error"]["code"] == "JOB_NOT_FOUND"

    # 4. /asr 无 Provider（种子全禁用）
    for p in client.get("/admin/providers", params={"kind": "asr"}).json():
        client.patch(f"/admin/providers/{p['id']}", json={"enabled": False})

    r4 = client.post("/asr", files={"audio": ("a.wav", b"RIFF", "audio/wav")})
    assert r4.status_code == 400
    assert r4.json()["error"]["code"] == "VALIDATION_ERROR"


def test_retry_failed_job(client, mock_all_registered, monkeypatch):
    """失败 Job 可通过 POST /jobs/<id>/retry 复用 job_id 重置为 pending，重新入队成功。"""
    from voxcraft.providers.mock import InMemoryMockAsrProvider

    # 1. 注入默认 Mock ASR
    p = client.post("/admin/providers", json={
        "kind": "asr", "name": "mock-asr",
        "class_name": "InMemoryMockAsrProvider", "config": {},
    }).json()
    client.post(f"/admin/providers/{p['id']}/set-default")

    # 2. 让首次 transcribe 抛错 → Job 落 failed
    calls = {"n": 0}
    original = InMemoryMockAsrProvider.transcribe

    def flaky(self, audio_path, language=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return original(self, audio_path, language=language)

    monkeypatch.setattr(InMemoryMockAsrProvider, "transcribe", flaky)

    r = client.post(
        "/asr", files={"audio": ("a.wav", b"RIFFfake", "audio/wav")},
        data={"language": "zh"},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert wait_for_job(client, job_id)["status"] == "failed"

    # 3. retry：复用 job_id，回到 pending → succeeded
    r2 = client.post(f"/jobs/{job_id}/retry")
    assert r2.status_code == 202
    assert r2.json()["job_id"] == job_id
    final = wait_for_job(client, job_id)
    assert final["status"] == "succeeded"
    assert final["error_code"] is None
    assert final["result"] is not None

    # 4. succeeded 状态不可再 retry
    r3 = client.post(f"/jobs/{job_id}/retry")
    assert r3.status_code == 400
    assert r3.json()["error"]["code"] == "VALIDATION_ERROR"


def test_mvp_smoke_models_library_flow(client, monkeypatch):
    """v0.1.2 模型库 smoke：catalog → 下载 → 自定义 → 删除。"""
    from pathlib import Path
    import time

    from voxcraft.models_lib import service as svc_mod

    def _fake(repo_id, local_dir, max_workers=8):
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "m.bin").write_bytes(b"x" * 128)
        return Path(local_dir)

    monkeypatch.setattr(svc_mod, "download_hf", _fake)
    monkeypatch.setattr(svc_mod, "download_ms", _fake)

    # 1. catalog 列表含 11 内置
    entries = client.get("/admin/models-library").json()
    builtins = [e for e in entries if e["is_builtin"]]
    assert len(builtins) == 11

    # 2. 下载 whisper-tiny
    r = client.post("/admin/models-library/whisper-tiny/download")
    assert r.status_code == 202
    mid = r.json()["id"]

    # 3. 等 ready
    for _ in range(60):
        vs = client.get("/admin/models-library").json()
        v = next(x for x in vs if x["model_id"] == mid)
        if v["status"] in ("ready", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert v["status"] == "ready"
    assert v["local_path"]

    # 4. 自定义添加
    r2 = client.post(
        "/admin/models-library/custom",
        json={
            "catalog_key": "custom_smoke",
            "source": "hf",
            "repo_id": "x/y",
            "kind": "asr",
        },
    )
    assert r2.status_code == 202

    # 5. 非 custom_ 前缀被拒
    r3 = client.post(
        "/admin/models-library/custom",
        json={"catalog_key": "bad", "source": "hf", "repo_id": "x/y", "kind": "asr"},
    )
    assert r3.status_code == 400

    # 6. 删除 ready 模型
    r4 = client.delete(f"/admin/models-library/{mid}")
    assert r4.status_code == 204
