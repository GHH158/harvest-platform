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
