import os

import pytest
from app.config import Settings
from app.db import apply_schema, make_engine
from app.repository import Repository
from sqlalchemy import text


@pytest.mark.integration
def test_recovery_attempt_limit_and_repeated_completion_are_safe() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    material_id, job_id = repository.create_material_with_job(
        title="integration test",
        source_type="paste",
        source_ref=None,
        job_kind="tts",
        payload={"text": "雨です。"},
    )
    segments = [{"idx": 0, "text_ja": "雨です。", "start_ms": 0, "end_ms": 1_000}]

    try:
        claimed = repository.claim_next_job(max_attempts=3)
        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.attempts == 1

        repository.complete_reading(
            material_id=material_id,
            local_path="/tmp/first.mp3",
            oss_key="materials/test/first.mp3",
            bytes_count=100,
            duration_ms=1_000,
            segments=segments,
        )
        repository.complete_reading(
            material_id=material_id,
            local_path="/tmp/second.mp3",
            oss_key="materials/test/second.mp3",
            bytes_count=200,
            duration_ms=1_000,
            segments=segments,
        )
        repository.replace_tokens(
            material_id,
            [{"segment_idx": 0, "idx": 0, "surface": "雨", "start_ms": 0, "end_ms": 500}],
        )
        assert repository.get_tokens(material_id)[0]["surface"] == "雨"
        with engine.connect() as connection:
            asset_count = connection.execute(
                text("SELECT count(*) FROM media_asset WHERE material_id = :material_id"),
                {"material_id": material_id},
            ).scalar_one()
        assert asset_count == 2

        with engine.begin() as connection:
            connection.execute(text("UPDATE job SET status = 'running' WHERE id = :job_id"), {"job_id": job_id})
            connection.execute(
                text("UPDATE material SET status = 'processing' WHERE id = :material_id"),
                {"material_id": material_id},
            )
        assert repository.recover_stale_running_jobs(stale_seconds=-1) == 1
        assert repository.get_job(job_id)["status"] == "pending"
        assert repository.get_material(material_id)["status"] == "pending"

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE job SET attempts = 3, status = 'pending' WHERE id = :job_id"),
                {"job_id": job_id},
            )
        assert repository.fail_exhausted_pending_jobs(max_attempts=3) == 1
        assert repository.get_job(job_id)["status"] == "failed"
        assert repository.get_material(material_id)["status"] == "failed"
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM material WHERE id = :material_id"), {"material_id": material_id})
        engine.dispose()


@pytest.mark.integration
def test_enhancement_and_shadowing_exhaustion_preserve_consumer_state() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    material_id, tts_job_id = repository.create_material_with_job(
        title="state machine integration test",
        source_type="paste",
        source_ref=None,
        job_kind="tts",
        payload={"text": "雨です。"},
    )
    segments = [{"idx": 0, "text_ja": "雨です。", "start_ms": 0, "end_ms": 1_000}]
    shadowing_job_id: int | None = None

    try:
        repository.complete_reading(
            material_id=material_id,
            local_path="/tmp/state-machine.mp3",
            oss_key="materials/test/state-machine.mp3",
            bytes_count=100,
            duration_ms=1_000,
            segments=segments,
        )
        asr_job_id = repository.enqueue_job(
            kind="asr",
            material_id=material_id,
            payload={"text": "雨です。", "audio_url": "https://example.com/reading.mp3"},
        )
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE job SET status = 'pending', attempts = 3 WHERE id = :job_id"),
                {"job_id": asr_job_id},
            )
        assert repository.fail_exhausted_pending_jobs(max_attempts=3) == 1
        assert repository.get_job(asr_job_id)["status"] == "failed"
        assert repository.get_material(material_id)["status"] == "ready"

        segment_id = repository.get_segments(material_id)[0]["id"]
        attempt_id, shadowing_job_id = repository.create_shadowing_submission(
            segment_id, "/tmp/shadowing.m4a"
        )
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE job SET status = 'pending', attempts = 3 WHERE id = :job_id"),
                {"job_id": shadowing_job_id},
            )
        assert repository.fail_exhausted_pending_jobs(max_attempts=3) == 1
        attempt = repository.get_shadowing_attempt(attempt_id)
        assert attempt is not None
        assert attempt["status"] == "failed"
        assert attempt["job_id"] == shadowing_job_id
        assert repository.get_material(material_id)["status"] == "ready"
    finally:
        with engine.begin() as connection:
            if shadowing_job_id is not None:
                connection.execute(text("DELETE FROM job WHERE id = :job_id"), {"job_id": shadowing_job_id})
            connection.execute(text("DELETE FROM material WHERE id = :material_id"), {"material_id": material_id})
            connection.execute(text("DELETE FROM job WHERE id = :job_id"), {"job_id": tts_job_id})
        engine.dispose()


@pytest.mark.integration
def test_voice_profile_default_switch_is_persisted() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    created: list[int] = []
    try:
        first = repository.create_voice_profile(name="first", voice_id="voice-first")
        second = repository.create_voice_profile(name="second", voice_id="voice-second")
        created.extend([first, second])
        assert repository.default_voice_id() == "voice-second"

        assert repository.set_default_voice_profile(first) is True
        assert repository.default_voice_id() == "voice-first"
        profiles = repository.voice_profiles()
        assert sum(bool(profile["is_default"]) for profile in profiles if profile["id"] in created) == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM voice_profile WHERE id = ANY(:ids)"), {"ids": created})
        engine.dispose()
