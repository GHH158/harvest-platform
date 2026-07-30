from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    material_id: int | None
    payload: dict[str, Any]
    attempts: int


class Repository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_material_with_job(
        self,
        *,
        title: str,
        source_type: str,
        source_ref: str | None,
        job_kind: str,
        payload: dict[str, Any],
    ) -> tuple[int, int]:
        with self.engine.begin() as connection:
            material_id = connection.execute(
                text(
                    """
                    INSERT INTO material (kind, title, source_type, source_ref, status)
                    VALUES ('reading', :title, :source_type, :source_ref, 'pending')
                    RETURNING id
                    """
                ),
                {"title": title, "source_type": source_type, "source_ref": source_ref},
            ).scalar_one()
            job_id = connection.execute(
                text(
                    """
                    INSERT INTO job (kind, material_id, status, payload)
                    VALUES (:kind, :material_id, 'pending', CAST(:payload AS JSONB))
                    RETURNING id
                    """
                ),
                {
                    "kind": job_kind,
                    "material_id": material_id,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            ).scalar_one()
        return int(material_id), int(job_id)

    def get_material(self, material_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT m.*, delivery.oss_key AS audio_oss_key
                    FROM material m
                    LEFT JOIN LATERAL (
                        SELECT oss_key FROM media_asset
                        WHERE material_id = m.id AND kind = 'audio' AND purpose = 'delivery'
                        ORDER BY id DESC LIMIT 1
                    ) delivery ON true
                    WHERE m.id = :material_id
                    """
                    ),
                    {"material_id": material_id},
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def list_materials(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT m.*, delivery.oss_key AS audio_oss_key
                    FROM material m
                    LEFT JOIN LATERAL (
                        SELECT oss_key FROM media_asset
                        WHERE material_id = m.id AND kind = 'audio' AND purpose = 'delivery'
                        ORDER BY id DESC LIMIT 1
                    ) delivery ON true
                    ORDER BY m.created_at DESC
                    """
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def get_segments(self, material_id: int) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT id, material_id, idx, text_ja, text_zh, start_ms, end_ms
                    FROM segment WHERE material_id = :material_id ORDER BY idx
                    """
                    ),
                    {"material_id": material_id},
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM job WHERE id = :job_id"), {"job_id": job_id}).mappings().first()
        return dict(row) if row else None

    def claim_next_job(self, *, max_attempts: int) -> Job | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    WITH next_job AS (
                        SELECT id FROM job
                        WHERE status = 'pending' AND attempts < :max_attempts
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE job
                    SET status = 'running', attempts = attempts + 1
                    FROM next_job
                    WHERE job.id = next_job.id
                    RETURNING job.id, job.kind, job.material_id, job.payload, job.attempts
                    """
                    ),
                    {"max_attempts": max_attempts},
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return Job(
            id=int(row["id"]),
            kind=str(row["kind"]),
            material_id=int(row["material_id"]) if row["material_id"] is not None else None,
            payload=dict(row["payload"] or {}),
            attempts=int(row["attempts"]),
        )

    def recover_stale_running_jobs(self, *, stale_seconds: int) -> int:
        """Requeue jobs abandoned by a worker process that ended unexpectedly."""
        with self.engine.begin() as connection:
            rows = connection.execute(
                text(
                    """
                    WITH recovered AS (
                        UPDATE job
                        SET status = 'pending', error_message = 'Worker interrupted; automatically requeued.'
                        WHERE status = 'running'
                          AND updated_at < now() - (:stale_seconds * interval '1 second')
                        RETURNING material_id
                    )
                    UPDATE material
                    SET status = 'pending', error_message = NULL
                    WHERE status = 'processing'
                      AND id IN (SELECT material_id FROM recovered WHERE material_id IS NOT NULL)
                    RETURNING id
                    """
                ),
                {"stale_seconds": stale_seconds},
            ).all()
        return len(rows)

    def fail_exhausted_pending_jobs(self, *, max_attempts: int) -> int:
        """Stop a repeatedly interrupted job from looping forever."""
        message = f"Worker stopped after {max_attempts} interrupted attempts."
        with self.engine.begin() as connection:
            rows = connection.execute(
                text(
                    """
                    WITH exhausted AS (
                        UPDATE job
                        SET status = 'failed', error_message = :message
                        WHERE status = 'pending' AND attempts >= :max_attempts
                        RETURNING material_id
                    )
                    UPDATE material
                    SET status = 'failed', error_message = :message
                    WHERE id IN (SELECT material_id FROM exhausted WHERE material_id IS NOT NULL)
                    RETURNING id
                    """
                ),
                {"max_attempts": max_attempts, "message": message},
            ).all()
        return len(rows)

    def enqueue_job(self, *, kind: str, material_id: int, payload: dict[str, Any]) -> int:
        with self.engine.begin() as connection:
            job_id = connection.execute(
                text(
                    """
                    INSERT INTO job (kind, material_id, status, payload)
                    VALUES (:kind, :material_id, 'pending', CAST(:payload AS JSONB))
                    RETURNING id
                    """
                ),
                {
                    "kind": kind,
                    "material_id": material_id,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            ).scalar_one()
        return int(job_id)

    def update_material_title(self, material_id: int, title: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE material SET title = :title WHERE id = :material_id"),
                {"material_id": material_id, "title": title},
            )

    def mark_job_done(self, job_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE job SET status = 'done' WHERE id = :job_id"), {"job_id": job_id})

    def mark_job_failed(self, job_id: int, material_id: int | None, message: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE job SET status = 'failed', error_message = :message WHERE id = :job_id"),
                {"job_id": job_id, "message": message},
            )
            if material_id is not None:
                connection.execute(
                    text(
                        """
                        UPDATE material SET status = 'failed', error_message = :message
                        WHERE id = :material_id
                        """
                    ),
                    {"material_id": material_id, "message": message},
                )

    def mark_material_processing(self, material_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE material SET status = 'processing', error_message = NULL WHERE id = :material_id"),
                {"material_id": material_id},
            )

    def complete_reading(
        self,
        *,
        material_id: int,
        local_path: str,
        oss_key: str,
        bytes_count: int,
        duration_ms: int,
        segments: list[dict[str, Any]],
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM media_asset WHERE material_id = :material_id"),
                {"material_id": material_id},
            )
            connection.execute(
                text("DELETE FROM segment WHERE material_id = :material_id"),
                {"material_id": material_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO media_asset (material_id, kind, purpose, local_path, bytes, duration_ms)
                    VALUES (:material_id, 'audio', 'archive', :local_path, :bytes_count, :duration_ms)
                    """
                ),
                {
                    "material_id": material_id,
                    "local_path": local_path,
                    "bytes_count": bytes_count,
                    "duration_ms": duration_ms,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO media_asset (material_id, kind, purpose, oss_key, bytes, duration_ms)
                    VALUES (:material_id, 'audio', 'delivery', :oss_key, :bytes_count, :duration_ms)
                    """
                ),
                {
                    "material_id": material_id,
                    "oss_key": oss_key,
                    "bytes_count": bytes_count,
                    "duration_ms": duration_ms,
                },
            )
            for segment in segments:
                connection.execute(
                    text(
                        """
                        INSERT INTO segment (material_id, idx, text_ja, start_ms, end_ms)
                        VALUES (:material_id, :idx, :text_ja, :start_ms, :end_ms)
                        """
                    ),
                    {"material_id": material_id, **segment},
                )
            connection.execute(
                text(
                    """
                    UPDATE material SET status = 'ready', duration_ms = :duration_ms, error_message = NULL
                    WHERE id = :material_id
                    """
                ),
                {"material_id": material_id, "duration_ms": duration_ms},
            )
