from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
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
        kind: str = "reading",
    ) -> tuple[int, int]:
        with self.engine.begin() as connection:
            material_id = connection.execute(
                text(
                    """
                    INSERT INTO material (kind, title, source_type, source_ref, status)
                    VALUES (:kind, :title, :source_type, :source_ref, 'pending')
                    RETURNING id
                    """
                ),
                {"kind": kind, "title": title, "source_type": source_type, "source_ref": source_ref},
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
                    SELECT m.*, delivery.oss_key AS audio_oss_key, video_delivery.oss_key AS video_oss_key
                    FROM material m
                    LEFT JOIN LATERAL (
                        SELECT oss_key FROM media_asset
                        WHERE material_id = m.id AND kind = 'audio' AND purpose = 'delivery'
                        ORDER BY id DESC LIMIT 1
                    ) delivery ON true
                    LEFT JOIN LATERAL (
                        SELECT oss_key FROM media_asset WHERE material_id = m.id AND kind = 'video' AND purpose = 'delivery'
                        ORDER BY id DESC LIMIT 1
                    ) video_delivery ON true
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
                    SELECT m.*, delivery.oss_key AS audio_oss_key, video_delivery.oss_key AS video_oss_key
                    FROM material m
                    LEFT JOIN LATERAL (
                        SELECT oss_key FROM media_asset
                        WHERE material_id = m.id AND kind = 'audio' AND purpose = 'delivery'
                        ORDER BY id DESC LIMIT 1
                    ) delivery ON true
                    LEFT JOIN LATERAL (
                        SELECT oss_key FROM media_asset WHERE material_id = m.id AND kind = 'video' AND purpose = 'delivery'
                        ORDER BY id DESC LIMIT 1
                    ) video_delivery ON true
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

    def get_tokens(self, material_id: int) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT t.id, t.segment_id, t.idx, t.surface, t.start_ms, t.end_ms
                    FROM token t
                    JOIN segment s ON s.id = t.segment_id
                    WHERE s.material_id = :material_id
                    ORDER BY s.idx, t.idx
                    """
                    ),
                    {"material_id": material_id},
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def segment_context(self, material_id: int, segment_id: int, radius: int = 2) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            current_idx = connection.execute(
                text("SELECT idx FROM segment WHERE id = :segment_id AND material_id = :material_id"),
                {"segment_id": segment_id, "material_id": material_id},
            ).scalar_one_or_none()
            if current_idx is None:
                return []
            rows = connection.execute(
                text(
                    """SELECT id, idx, text_ja, text_zh FROM segment
                    WHERE material_id = :material_id AND idx BETWEEN :start AND :end ORDER BY idx"""
                ),
                {"material_id": material_id, "start": int(current_idx) - radius, "end": int(current_idx) + radius},
            ).mappings().all()
        return [dict(row) for row in rows]

    def add_companion_message(self, material_id: int, segment_id: int | None, role: str, content: str) -> dict[str, Any]:
        with self.engine.begin() as connection:
            row = connection.execute(
                text("""INSERT INTO companion_message (material_id, segment_id, role, content)
                VALUES (:material_id, :segment_id, :role, :content) RETURNING *"""),
                {"material_id": material_id, "segment_id": segment_id, "role": role, "content": content},
            ).mappings().one()
        return dict(row)

    def companion_messages(self, material_id: int) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM companion_message WHERE material_id = :material_id ORDER BY id"),
                {"material_id": material_id},
            ).mappings().all()
        return [dict(row) for row in rows]

    def add_chat_message(self, session_id: str, role: str, content: str) -> dict[str, Any]:
        with self.engine.begin() as connection:
            row = connection.execute(
                text("INSERT INTO chat_message (session_id, role, content) VALUES (:session_id, :role, :content) RETURNING *"),
                {"session_id": session_id, "role": role, "content": content},
            ).mappings().one()
        return dict(row)

    def chat_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM chat_message WHERE session_id = :session_id ORDER BY id"),
                {"session_id": session_id},
            ).mappings().all()
        return [dict(row) for row in rows]

    def voice_profiles(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM voice_profile ORDER BY is_default DESC, id DESC")
            ).mappings().all()
        return [dict(row) for row in rows]

    def default_voice_id(self) -> str | None:
        with self.engine.connect() as connection:
            value = connection.execute(
                text("SELECT voice_id FROM voice_profile WHERE is_default = true ORDER BY id DESC LIMIT 1")
            ).scalar_one_or_none()
        return str(value) if value else None

    def create_voice_profile(self, *, name: str, voice_id: str, provider: str = "alibaba") -> int:
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE voice_profile SET is_default = false WHERE is_default = true"))
            profile_id = connection.execute(
                text(
                    """INSERT INTO voice_profile (name, provider, voice_id, is_default)
                    VALUES (:name, :provider, :voice_id, true) RETURNING id"""
                ),
                {"name": name, "provider": provider, "voice_id": voice_id},
            ).scalar_one()
        return int(profile_id)

    def set_default_voice_profile(self, profile_id: int) -> bool:
        with self.engine.begin() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM voice_profile WHERE id = :profile_id"), {"profile_id": profile_id}
            ).scalar_one_or_none()
            if exists is None:
                return False
            connection.execute(text("UPDATE voice_profile SET is_default = false WHERE is_default = true"))
            connection.execute(
                text("UPDATE voice_profile SET is_default = true WHERE id = :profile_id"), {"profile_id": profile_id}
            )
        return True

    def replace_tokens(self, material_id: int, tokens: list[dict[str, Any]]) -> None:
        """Atomically replace P2 token timestamps without changing source text."""
        with self.engine.begin() as connection:
            segment_rows = (
                connection.execute(
                    text("SELECT id, idx FROM segment WHERE material_id = :material_id"),
                    {"material_id": material_id},
                )
                .mappings()
                .all()
            )
            segment_ids = {int(row["idx"]): int(row["id"]) for row in segment_rows}
            connection.execute(
                text(
                    """
                    DELETE FROM token
                    WHERE segment_id IN (SELECT id FROM segment WHERE material_id = :material_id)
                    """
                ),
                {"material_id": material_id},
            )
            for token in tokens:
                segment_id = segment_ids.get(int(token["segment_idx"]))
                if segment_id is None:
                    continue
                connection.execute(
                    text(
                        """
                        INSERT INTO token (segment_id, idx, surface, start_ms, end_ms)
                        VALUES (:segment_id, :idx, :surface, :start_ms, :end_ms)
                        """
                    ),
                    {"segment_id": segment_id, **token},
                )

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
                    UPDATE job
                    SET status = 'failed', error_message = :message
                    WHERE status = 'pending' AND attempts >= :max_attempts
                    RETURNING material_id, kind, payload
                    """
                ),
                {"max_attempts": max_attempts, "message": message},
            ).mappings().all()
            for row in rows:
                material_id = row["material_id"]
                if material_id is not None and row["kind"] != "asr":
                    connection.execute(
                        text("UPDATE material SET status = 'failed', error_message = :message WHERE id = :material_id"),
                        {"material_id": material_id, "message": message},
                    )
                if row["kind"] == "shadowing":
                    attempt_id = int((row["payload"] or {}).get("attempt_id", 0))
                    if attempt_id:
                        connection.execute(
                            text(
                                """UPDATE shadowing_attempt
                                SET status = 'failed', error_message = :message
                                WHERE id = :attempt_id"""
                            ),
                            {"attempt_id": attempt_id, "message": message},
                        )
        return len(rows)

    def enqueue_job(self, *, kind: str, material_id: int | None, payload: dict[str, Any]) -> int:
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

    def get_segment(self, segment_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM segment WHERE id = :segment_id"), {"segment_id": segment_id}
            ).mappings().first()
        return dict(row) if row else None

    def create_shadowing_submission(self, segment_id: int, audio_path: str) -> tuple[int, int]:
        """Create the attempt and its job atomically after the upload is safely on disk."""
        with self.engine.begin() as connection:
            attempt_id = int(
                connection.execute(
                    text(
                        """INSERT INTO shadowing_attempt (segment_id, audio_path, status)
                        VALUES (:segment_id, :audio_path, 'processing') RETURNING id"""
                    ),
                    {"segment_id": segment_id, "audio_path": audio_path},
                ).scalar_one()
            )
            payload = json.dumps(
                {"attempt_id": attempt_id, "segment_id": segment_id, "audio_path": audio_path},
                ensure_ascii=False,
            )
            job_id = int(
                connection.execute(
                    text(
                        """INSERT INTO job (kind, material_id, status, payload)
                        VALUES ('shadowing', NULL, 'pending', CAST(:payload AS JSONB)) RETURNING id"""
                    ),
                    {"payload": payload},
                ).scalar_one()
            )
            connection.execute(
                text("UPDATE shadowing_attempt SET job_id = :job_id WHERE id = :attempt_id"),
                {"attempt_id": attempt_id, "job_id": job_id},
            )
        return attempt_id, job_id

    def complete_shadowing_attempt(self, attempt_id: int, transcript: str, diff: list[dict[str, Any]], score: float) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("""UPDATE shadowing_attempt SET asr_text = :transcript,
                    diff_json = CAST(:diff AS JSONB), score = :score, status = 'ready', error_message = NULL
                    WHERE id = :attempt_id"""),
                {"attempt_id": attempt_id, "transcript": transcript, "diff": json.dumps(diff, ensure_ascii=False),
                 "score": score},
            )

    def get_shadowing_attempt(self, attempt_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM shadowing_attempt WHERE id = :attempt_id"), {"attempt_id": attempt_id}
            ).mappings().first()
        return dict(row) if row else None

    def fail_shadowing_attempt(self, attempt_id: int, message: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE shadowing_attempt SET status = 'failed', error_message = :message WHERE id = :attempt_id"),
                {"attempt_id": attempt_id, "message": message},
            )

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

    def store_video_assets(
        self,
        *,
        material_id: int,
        source_path: str,
        video_playlist_path: str,
        audio_playlist_path: str,
        video_playlist_key: str,
        audio_playlist_key: str,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM media_asset WHERE material_id = :material_id"),
                {"material_id": material_id},
            )
            connection.execute(
                text("""INSERT INTO media_asset (material_id, kind, purpose, local_path, bytes)
                VALUES (:material_id, 'video', 'archive', :local_path, :bytes)"""),
                {"material_id": material_id, "local_path": source_path, "bytes": Path(source_path).stat().st_size},
            )
            for kind, local_path, oss_key in (
                ("video", video_playlist_path, video_playlist_key),
                ("audio", audio_playlist_path, audio_playlist_key),
            ):
                playlist = Path(local_path)
                connection.execute(
                    text("""INSERT INTO media_asset (material_id, kind, purpose, local_path, oss_key, bytes)
                    VALUES (:material_id, :kind, 'delivery', :local_path, :oss_key, :bytes)"""),
                    {
                        "material_id": material_id,
                        "kind": kind,
                        "local_path": local_path,
                        "oss_key": oss_key,
                        "bytes": sum(path.stat().st_size for path in playlist.parent.rglob("*") if path.is_file()),
                    },
                )

    def replace_video_segments(self, material_id: int, segments: list[dict[str, Any]]) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM segment WHERE material_id = :material_id"),
                {"material_id": material_id},
            )
            for segment in segments:
                connection.execute(
                    text("""INSERT INTO segment (material_id, idx, text_ja, start_ms, end_ms)
                    VALUES (:material_id, :idx, :text_ja, :start_ms, :end_ms)"""),
                    {"material_id": material_id, **segment},
                )

    def complete_video_translation(self, material_id: int, translations: list[str]) -> None:
        with self.engine.begin() as connection:
            for idx, translation in enumerate(translations):
                connection.execute(
                    text("UPDATE segment SET text_zh = :text_zh WHERE material_id = :material_id AND idx = :idx"),
                    {"material_id": material_id, "idx": idx, "text_zh": translation},
                )
            duration_ms = connection.execute(
                text("SELECT max(end_ms) FROM segment WHERE material_id = :material_id"), {"material_id": material_id}
            ).scalar_one_or_none()
            connection.execute(
                text(
                    """UPDATE material SET status = 'ready', duration_ms = :duration_ms, error_message = NULL
                    WHERE id = :material_id"""
                ),
                {"material_id": material_id, "duration_ms": duration_ms},
            )
