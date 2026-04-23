"""/jobs/* 集成测试：手动在 DB 插入 Job 记录，验证查询/下载/删除。"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session

from voxcraft.db.engine import get_engine
from voxcraft.db.models import Job


def _insert_job(**overrides):
    defaults = dict(
        id="job-1",
        kind="asr",
        status="succeeded",
        request={"audio": "a.wav"},
        result={"text": "hi"},
        progress=1.0,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    with Session(get_engine()) as s:
        j = Job(**defaults)
        s.add(j)
        s.commit()
        s.refresh(j)
        return j


def test_list_jobs_empty(client):
    r = client.get("/jobs")
    assert r.status_code == 200
    assert r.json() == []


def test_list_and_filter_by_kind(client):
    _insert_job(id="j-asr", kind="asr")
    _insert_job(id="j-tts", kind="tts")
    r = client.get("/jobs", params={"kind": "asr"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["kind"] == "asr"


def test_get_job_by_id(client):
    _insert_job(id="j-abc")
    r = client.get("/jobs/j-abc")
    assert r.status_code == 200
    assert r.json()["id"] == "j-abc"


def test_get_missing_job_returns_404(client):
    r = client.get("/jobs/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_delete_job(client):
    _insert_job(id="j-del")
    r = client.delete("/jobs/j-del")
    assert r.status_code == 204
    r2 = client.get("/jobs/j-del")
    assert r2.status_code == 404


def test_download_output_not_ready(client):
    _insert_job(id="j-no-out", output_path=None)
    r = client.get("/jobs/j-no-out/output")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "JOB_OUTPUT_NOT_READY"


def test_download_output_missing_on_disk(client):
    _insert_job(id="j-gone", output_path="/tmp/definitely-not-here-xyz.wav")
    r = client.get("/jobs/j-gone/output")
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "JOB_OUTPUT_MISSING"


def test_download_output_streams_file(client, tmp_path):
    audio = tmp_path / "out.wav"
    audio.write_bytes(b"RIFFmockwavdata")
    _insert_job(id="j-ok", output_path=str(audio))

    r = client.get("/jobs/j-ok/output")
    assert r.status_code == 200
    assert r.content == b"RIFFmockwavdata"
    assert "attachment" in r.headers.get("content-disposition", "")


def test_preview_output_is_inline(client, tmp_path):
    audio = tmp_path / "preview.wav"
    audio.write_bytes(b"RIFF-preview")
    _insert_job(id="j-prev", output_path=str(audio))

    r = client.get("/jobs/j-prev/output/preview")
    assert r.status_code == 200
    # 无 attachment；浏览器 <audio> 可直接引用
    assert "attachment" not in r.headers.get("content-disposition", "")


def test_separator_multi_output_key(client, tmp_path):
    v = tmp_path / "v.wav"
    i = tmp_path / "i.wav"
    v.write_bytes(b"vocals")
    i.write_bytes(b"instrumental")
    _insert_job(
        id="j-sep",
        kind="separate",
        output_extras={"vocals": str(v), "instrumental": str(i)},
    )

    r_v = client.get("/jobs/j-sep/output", params={"key": "vocals"})
    assert r_v.status_code == 200
    assert r_v.content == b"vocals"

    r_i = client.get("/jobs/j-sep/output", params={"key": "instrumental"})
    assert r_i.content == b"instrumental"
