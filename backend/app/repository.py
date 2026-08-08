from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from .chat import build_correction_guidance
from .grammar_catalogue import catalogue_rows
from .text import canonical_source_key


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

    def find_material_by_source_url(self, url: str) -> dict[str, Any] | None:
        """Existing material imported from the same source, ignoring share noise.

        Compared in Python rather than SQL because the canonical form cannot be
        expressed as a plain column match; a personal library is small enough
        that scanning the URL-sourced rows is cheaper than storing a second key.
        """
        key = canonical_source_key(url)
        if not key:
            return None
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT id, title, status, source_ref FROM material
                       WHERE source_type = 'url' AND source_ref IS NOT NULL
                       ORDER BY id"""
                )
            ).mappings().all()
        for row in rows:
            if canonical_source_key(row["source_ref"]) == key:
                return dict(row)
        return None

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
                    SELECT m.*, delivery.oss_key AS audio_oss_key, video_delivery.oss_key AS video_oss_key,
                           current_job.id AS current_job_id, current_job.kind AS current_job_kind,
                           current_job.status AS current_job_status,
                           current_job.error_message AS current_job_error_message,
                           current_job.payload AS current_job_payload,
                           current_job.updated_at AS current_job_updated_at,
                           thumbnail.local_path AS thumbnail_local_path
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
                    LEFT JOIN LATERAL (
                        SELECT id, kind, status, error_message, payload, updated_at
                        FROM job WHERE material_id = m.id
                        ORDER BY id DESC LIMIT 1
                    ) current_job ON true
                    LEFT JOIN LATERAL (
                        SELECT local_path FROM media_asset
                        WHERE material_id = m.id AND kind = 'image' AND purpose = 'thumbnail'
                        ORDER BY id DESC LIMIT 1
                    ) thumbnail ON true
                    WHERE m.id = :material_id
                    """
                    ),
                    {"material_id": material_id},
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def get_playback_state(self, material_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT m.id AS material_id,
                               COALESCE(state.position_ms, 0) AS position_ms,
                               state.updated_at
                        FROM material m
                        LEFT JOIN material_playback_state state ON state.material_id = m.id
                        WHERE m.id = :material_id
                        """
                    ),
                    {"material_id": material_id},
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def save_playback_state(self, material_id: int, position_ms: int) -> dict[str, Any] | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        INSERT INTO material_playback_state (material_id, position_ms)
                        SELECT id, :position_ms FROM material
                        WHERE id = :material_id
                        ON CONFLICT (material_id) DO UPDATE
                        SET position_ms = EXCLUDED.position_ms
                        RETURNING material_id, position_ms, updated_at
                        """
                    ),
                    {"material_id": material_id, "position_ms": position_ms},
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def list_materials(
        self,
        *,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        parameters: dict[str, Any] = {"offset": offset}
        if status:
            conditions.append("m.status = :status")
            parameters["status"] = status
        where_clause = " AND ".join(conditions) if conditions else "true"
        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT :limit"
            parameters["limit"] = limit
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        f"""
                    SELECT m.*, delivery.oss_key AS audio_oss_key, video_delivery.oss_key AS video_oss_key,
                           current_job.id AS current_job_id, current_job.kind AS current_job_kind,
                           current_job.status AS current_job_status,
                           current_job.error_message AS current_job_error_message,
                           current_job.payload AS current_job_payload,
                           current_job.updated_at AS current_job_updated_at,
                           thumbnail.local_path AS thumbnail_local_path
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
                    LEFT JOIN LATERAL (
                        SELECT id, kind, status, error_message, payload, updated_at
                        FROM job WHERE material_id = m.id
                        ORDER BY id DESC LIMIT 1
                    ) current_job ON true
                    LEFT JOIN LATERAL (
                        SELECT local_path FROM media_asset
                        WHERE material_id = m.id AND kind = 'image' AND purpose = 'thumbnail'
                        ORDER BY id DESC LIMIT 1
                    ) thumbnail ON true
                    WHERE {where_clause}
                    ORDER BY m.created_at DESC, m.id DESC
                    {limit_clause} OFFSET :offset
                    """
                    ),
                    parameters,
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def count_materials(self, *, status: str | None = None) -> int:
        conditions: list[str] = []
        parameters: dict[str, Any] = {}
        if status:
            conditions.append("status = :status")
            parameters["status"] = status
        where_clause = " AND ".join(conditions) if conditions else "true"
        with self.engine.connect() as connection:
            return int(
                connection.execute(text(f"SELECT count(*) FROM material WHERE {where_clause}"), parameters).scalar_one()
            )

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
                    SELECT t.id, t.segment_id, t.idx, t.surface, t.reading, t.start_ms, t.end_ms
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

    def ensure_chat_session(self, session_id: str, topic: str = "旧版聊天") -> dict[str, Any]:
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    """INSERT INTO chat_session (id, topic)
                    VALUES (:session_id, :topic)
                    ON CONFLICT (id) DO UPDATE SET topic = chat_session.topic
                    RETURNING *"""
                ),
                {"session_id": session_id, "topic": topic},
            ).mappings().one()
        return dict(row)

    def create_chat_session(
        self,
        *,
        session_id: str,
        topic: str,
        starter_id: str | None,
        assistant_content: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with self.engine.begin() as connection:
            session = connection.execute(
                text(
                    """INSERT INTO chat_session (id, topic, starter_id)
                    VALUES (:session_id, :topic, :starter_id) RETURNING *"""
                ),
                {"session_id": session_id, "topic": topic, "starter_id": starter_id},
            ).mappings().one()
            assistant = connection.execute(
                text(
                    """INSERT INTO chat_message (session_id, role, content)
                    VALUES (:session_id, 'assistant', :content) RETURNING *"""
                ),
                {"session_id": session_id, "content": assistant_content},
            ).mappings().one()
        return dict(session), dict(assistant)

    def get_chat_session(self, session_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM chat_session WHERE id = :session_id"),
                {"session_id": session_id},
            ).mappings().first()
        return dict(row) if row else None

    def chat_sessions(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT s.*, latest.content AS last_message_preview
                    FROM chat_session s
                    LEFT JOIN LATERAL (
                        SELECT content FROM chat_message
                        WHERE session_id = s.id ORDER BY id DESC LIMIT 1
                    ) latest ON true
                    ORDER BY s.updated_at DESC, s.created_at DESC"""
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    def delete_chat_session(self, session_id: str) -> bool:
        with self.engine.begin() as connection:
            deleted = connection.execute(
                text("DELETE FROM chat_session WHERE id = :session_id RETURNING id"),
                {"session_id": session_id},
            ).scalar_one_or_none()
        return deleted is not None

    def add_chat_message(self, session_id: str, role: str, content: str) -> dict[str, Any]:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO chat_session (id, topic) VALUES (:session_id, '旧版聊天')
                    ON CONFLICT (id) DO NOTHING"""
                ),
                {"session_id": session_id},
            )
            row = connection.execute(
                text("INSERT INTO chat_message (session_id, role, content) VALUES (:session_id, :role, :content) RETURNING *"),
                {"session_id": session_id, "role": role, "content": content},
            ).mappings().one()
            connection.execute(
                text("UPDATE chat_session SET topic = topic WHERE id = :session_id"),
                {"session_id": session_id},
            )
        return dict(row)

    def chat_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM chat_message WHERE session_id = :session_id ORDER BY id"),
                {"session_id": session_id},
            ).mappings().all()
        return [dict(row) for row in rows]

    def chat_session_detail(self, session_id: str) -> dict[str, Any] | None:
        session = self.get_chat_session(session_id)
        if session is None:
            return None
        return {
            "session": session,
            "messages": self.chat_messages(session_id),
            "corrections": self.chat_corrections(session_id=session_id, limit=1_000),
        }

    def complete_chat_turn(
        self,
        *,
        session_id: str,
        user_content: str,
        assistant_content: str,
        correction: dict[str, Any] | None,
        create_session_topic: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
        with self.engine.begin() as connection:
            if create_session_topic is not None:
                connection.execute(
                    text(
                        """INSERT INTO chat_session (id, topic) VALUES (:session_id, :topic)
                        ON CONFLICT (id) DO NOTHING"""
                    ),
                    {"session_id": session_id, "topic": create_session_topic},
                )
            user = connection.execute(
                text(
                    """INSERT INTO chat_message (session_id, role, content)
                    VALUES (:session_id, 'user', :content) RETURNING *"""
                ),
                {"session_id": session_id, "content": user_content},
            ).mappings().one()
            stored_correction: dict[str, Any] | None = None
            if correction is not None:
                correction_row = connection.execute(
                    text(
                        """INSERT INTO chat_correction
                        (session_id, user_message_id, original_text, corrected_text, summary_zh)
                        VALUES (:session_id, :user_message_id, :original_text, :corrected_text, :summary_zh)
                        RETURNING *"""
                    ),
                    {
                        "session_id": session_id,
                        "user_message_id": int(user["id"]),
                        "original_text": user_content,
                        "corrected_text": correction["corrected_text"],
                        "summary_zh": correction["summary_zh"],
                    },
                ).mappings().one()
                items: list[dict[str, Any]] = []
                for index, item in enumerate(correction["items"]):
                    stored_item = connection.execute(
                        text(
                            """INSERT INTO chat_correction_item
                            (correction_id, idx, original_fragment, replacement, reason_zh, category)
                            VALUES (:correction_id, :idx, :original, :replacement, :reason_zh, :category)
                            RETURNING id, correction_id, idx, original_fragment AS original,
                                replacement, reason_zh, category"""
                        ),
                        {"correction_id": int(correction_row["id"]), "idx": index, **item},
                    ).mappings().one()
                    items.append(dict(stored_item))
                stored_correction = dict(correction_row)
                stored_correction["items"] = items
            assistant = connection.execute(
                text(
                    """INSERT INTO chat_message (session_id, role, content)
                    VALUES (:session_id, 'assistant', :content) RETURNING *"""
                ),
                {"session_id": session_id, "content": assistant_content},
            ).mappings().one()
            connection.execute(
                text("UPDATE chat_session SET topic = topic WHERE id = :session_id"),
                {"session_id": session_id},
            )
        return dict(user), stored_correction, dict(assistant)

    def chat_corrections(
        self,
        *,
        query: str = "",
        topic: str | None = None,
        category: str | None = None,
        cursor: int | None = None,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clean_query = query.strip()
        conditions: list[str] = []
        parameters: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            conditions.append("c.id < :cursor")
            parameters["cursor"] = cursor
        if session_id is not None:
            conditions.append("c.session_id = :session_id")
            parameters["session_id"] = session_id
        if topic is not None:
            conditions.append("s.topic = :topic")
            parameters["topic"] = topic
        if category is not None:
            conditions.append(
                """EXISTS (
                    SELECT 1 FROM chat_correction_item ci
                    WHERE ci.correction_id = c.id AND ci.category = :category
                )"""
            )
            parameters["category"] = category
        if clean_query:
            conditions.append(
                """(
                    c.original_text ILIKE :query_pattern
                    OR c.corrected_text ILIKE :query_pattern
                    OR c.summary_zh ILIKE :query_pattern
                    OR s.topic ILIKE :query_pattern
                    OR EXISTS (
                        SELECT 1 FROM chat_correction_item qi
                        WHERE qi.correction_id = c.id
                          AND (qi.original_fragment ILIKE :query_pattern
                            OR qi.replacement ILIKE :query_pattern
                            OR qi.reason_zh ILIKE :query_pattern)
                    )
                )"""
            )
            parameters["query_pattern"] = f"%{clean_query}%"
        where_clause = " AND ".join(conditions) if conditions else "true"
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""SELECT c.*, s.topic
                    FROM chat_correction c
                    JOIN chat_session s ON s.id = c.session_id
                    WHERE {where_clause}
                    ORDER BY c.id DESC LIMIT :limit"""
                ),
                parameters,
            ).mappings().all()
            result = [dict(row) for row in rows]
            correction_ids = [int(row["id"]) for row in result]
            if correction_ids:
                items = connection.execute(
                    text(
                        """SELECT id, correction_id, idx, original_fragment AS original,
                            replacement, reason_zh, category
                        FROM chat_correction_item
                        WHERE correction_id = ANY(:correction_ids)
                        ORDER BY correction_id, idx"""
                    ),
                    {"correction_ids": correction_ids},
                ).mappings().all()
                grouped: dict[int, list[dict[str, Any]]] = {}
                for item in items:
                    grouped.setdefault(int(item["correction_id"]), []).append(dict(item))
                for correction_row in result:
                    correction_row["items"] = grouped.get(int(correction_row["id"]), [])
        return result

    def delete_chat_correction(self, correction_id: int) -> bool:
        with self.engine.begin() as connection:
            deleted = connection.execute(
                text("DELETE FROM chat_correction WHERE id = :correction_id RETURNING id"),
                {"correction_id": correction_id},
            ).scalar_one_or_none()
        return deleted is not None

    def recent_correction_guidance(self, *, limit: int = 30, max_characters: int = 600) -> str:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT ci.category, ci.original_fragment, ci.replacement, ci.reason_zh
                    FROM chat_correction_item ci
                    JOIN chat_correction c ON c.id = ci.correction_id
                    ORDER BY c.created_at DESC, ci.id DESC LIMIT :limit"""
                ),
                {"limit": limit},
            ).mappings().all()
        return build_correction_guidance(rows, max_characters=max_characters)

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
                        INSERT INTO token (segment_id, idx, surface, reading, start_ms, end_ms)
                        VALUES (:segment_id, :idx, :surface, :reading, :start_ms, :end_ms)
                        """
                    ),
                    {"segment_id": segment_id, "reading": token.get("reading"), **token},
                )

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM job WHERE id = :job_id"), {"job_id": job_id}).mappings().first()
        return dict(row) if row else None

    def list_jobs(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        parameters: dict[str, Any] = {"offset": offset}
        if status:
            conditions.append("j.status = :status")
            parameters["status"] = status
        if kind:
            conditions.append("j.kind = :kind")
            parameters["kind"] = kind
        where_clause = " AND ".join(conditions) if conditions else "true"
        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT :limit"
            parameters["limit"] = limit
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""SELECT j.id, j.kind, j.material_id, j.status, j.error_message, j.attempts,
                        j.created_at, j.updated_at, m.title AS material_title
                    FROM job j
                    LEFT JOIN material m ON m.id = j.material_id
                    WHERE {where_clause}
                    ORDER BY j.created_at DESC, j.id DESC
                    {limit_clause} OFFSET :offset"""
                ),
                parameters,
            ).mappings().all()
        return [dict(row) for row in rows]

    def count_jobs(self, *, status: str | None = None, kind: str | None = None) -> int:
        conditions: list[str] = []
        parameters: dict[str, Any] = {}
        if status:
            conditions.append("status = :status")
            parameters["status"] = status
        if kind:
            conditions.append("kind = :kind")
            parameters["kind"] = kind
        where_clause = " AND ".join(conditions) if conditions else "true"
        with self.engine.connect() as connection:
            return int(
                connection.execute(text(f"SELECT count(*) FROM job WHERE {where_clause}"), parameters).scalar_one()
            )

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

    def latest_transcode_payload(self, material_id: int) -> dict[str, Any] | None:
        """Local paths produced by the most recent transcode of a video material."""
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload FROM job WHERE kind = 'transcode' AND material_id = :material_id "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"material_id": material_id},
            ).mappings().first()
        return dict(row["payload"]) if row and row["payload"] else None

    def merge_job_payload(self, job_id: int, values: dict[str, Any]) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """UPDATE job
                    SET payload = COALESCE(payload, '{}'::jsonb) || CAST(:values AS JSONB)
                    WHERE id = :job_id"""
                ),
                {"job_id": job_id, "values": json.dumps(values, ensure_ascii=False)},
            )

    def store_material_thumbnail(self, material_id: int, local_path: str) -> None:
        thumbnail = Path(local_path)
        if not thumbnail.exists():
            raise FileNotFoundError(local_path)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM media_asset WHERE material_id = :material_id "
                    "AND kind = 'image' AND purpose = 'thumbnail'"
                ),
                {"material_id": material_id},
            )
            connection.execute(
                text(
                    """INSERT INTO media_asset (material_id, kind, purpose, local_path, bytes)
                    VALUES (:material_id, 'image', 'thumbnail', :local_path, :bytes)"""
                ),
                {
                    "material_id": material_id,
                    "local_path": str(thumbnail),
                    "bytes": thumbnail.stat().st_size,
                },
            )

    def material_thumbnail_path(self, material_id: int) -> str | None:
        with self.engine.connect() as connection:
            path = connection.execute(
                text(
                    """SELECT local_path FROM media_asset
                    WHERE material_id = :material_id AND kind = 'image' AND purpose = 'thumbnail'
                    ORDER BY id DESC LIMIT 1"""
                ),
                {"material_id": material_id},
            ).scalar_one_or_none()
        return str(path) if path else None

    def retry_failed_material(self, material_id: int) -> int | None:
        """Requeue the latest failed material job without duplicating the material."""
        with self.engine.begin() as connection:
            material_exists = connection.execute(
                text("SELECT 1 FROM material WHERE id = :material_id"),
                {"material_id": material_id},
            ).scalar_one_or_none()
            if material_exists is None:
                return None
            job_id = connection.execute(
                text(
                    """SELECT id FROM job
                    WHERE material_id = :material_id AND status = 'failed'
                    ORDER BY id DESC LIMIT 1 FOR UPDATE"""
                ),
                {"material_id": material_id},
            ).scalar_one_or_none()
            if job_id is None:
                return 0
            connection.execute(
                text(
                    """UPDATE job SET status = 'pending', attempts = 0, error_message = NULL
                    WHERE id = :job_id"""
                ),
                {"job_id": job_id},
            )
            connection.execute(
                text(
                    """UPDATE material SET status = 'pending', error_message = NULL
                    WHERE id = :material_id"""
                ),
                {"material_id": material_id},
            )
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

    def mark_material_downloaded(self, material_id: int, duration_ms: int | None = None) -> None:
        """Video downloaded + transcoded locally; awaiting a manual transcription trigger."""
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """UPDATE material
                    SET status = 'downloaded', error_message = NULL,
                        duration_ms = COALESCE(:duration_ms, duration_ms)
                    WHERE id = :material_id"""
                ),
                {"material_id": material_id, "duration_ms": duration_ms},
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
                text(
                    "DELETE FROM media_asset WHERE material_id = :material_id "
                    "AND NOT (kind = 'image' AND purpose = 'thumbnail')"
                ),
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
                text(
                    "DELETE FROM media_asset WHERE material_id = :material_id "
                    "AND NOT (kind = 'image' AND purpose = 'thumbnail')"
                ),
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

    def save_segment_translations(self, material_id: int, translations: list[str], *, offset: int = 0) -> None:
        """Write the Chinese line only. Becoming consumable is a separate step —
        translation is an enhancement and must not be what flips `material.status`.

        `offset` is the segment index the batch starts at, so a long transcript can be
        translated in batches and keep whatever finished if a later batch fails."""
        with self.engine.begin() as connection:
            for position, translation in enumerate(translations):
                connection.execute(
                    text("UPDATE segment SET text_zh = :text_zh WHERE material_id = :material_id AND idx = :idx"),
                    {"material_id": material_id, "idx": offset + position, "text_zh": translation},
                )

    def translated_segment_indices(self, material_id: int) -> set[int]:
        """Segment indices that already carry a Chinese line.

        Lets a retried translation skip the batches that already landed instead of
        paying for them again — batches are saved atomically, so a stored index means
        its whole batch succeeded."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT idx FROM segment
                       WHERE material_id = :material_id
                         AND text_zh IS NOT NULL AND text_zh <> ''"""
                ),
                {"material_id": material_id},
            ).scalars().all()
        return {int(value) for value in rows}

    def mark_video_ready(self, material_id: int) -> None:
        """A video is consumable once its Japanese subtitles exist (§4.3): it plays,
        highlights per word and opens the companion. The Chinese line is optional."""
        with self.engine.begin() as connection:
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

    # ── grammar skeleton (§12) ──────────────────────────────────

    def sync_grammar_catalogue(self) -> None:
        """Upserts the catalogue. Only the index changes here; a learner's status
        rows and cached explanations are untouched, so extending the list later is
        a data change rather than a migration."""
        rows = catalogue_rows()
        if not rows:
            return
        with self.engine.begin() as connection:
            for row in rows:
                connection.execute(
                    text(
                        """INSERT INTO grammar_point (key, title_ja, title_zh, level, category, sort_order)
                           VALUES (:key, :title_ja, :title_zh, :level, :category, :sort_order)
                           ON CONFLICT (key) DO UPDATE SET
                             title_ja = EXCLUDED.title_ja,
                             title_zh = EXCLUDED.title_zh,
                             level = EXCLUDED.level,
                             category = EXCLUDED.category,
                             sort_order = EXCLUDED.sort_order"""
                    ),
                    row,
                )

    def list_grammar_points(self) -> list[dict[str, Any]]:
        """The whole skeleton with the learner's state. A missing encounter row
        means 未接触 — absence is the third state, not a stored value."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT p.id, p.key, p.title_ja, p.title_zh, p.level, p.category,
                              e.status, e.first_source, e.note, e.updated_at,
                              (x.point_id IS NOT NULL) AS has_explanation
                       FROM grammar_point p
                       LEFT JOIN grammar_encounter e ON e.point_id = p.id
                       LEFT JOIN grammar_explanation x ON x.point_id = p.id
                       ORDER BY p.level, p.sort_order, p.id"""
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    def get_grammar_point(self, key: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """SELECT p.*, e.status, e.note, x.content AS explanation
                       FROM grammar_point p
                       LEFT JOIN grammar_encounter e ON e.point_id = p.id
                       LEFT JOIN grammar_explanation x ON x.point_id = p.id
                       WHERE p.key = :key"""
                ),
                {"key": key},
            ).mappings().one_or_none()
        return dict(row) if row else None

    def mark_grammar_encounter(
        self, key: str, *, status: str, source: str | None = None, note: str | None = None
    ) -> dict[str, Any] | None:
        """Records or upgrades the learner's relationship with a point.

        Never downgrades: once something is 已弄懂, a later automatic 已撞见 from a
        correction must not silently undo that."""
        with self.engine.begin() as connection:
            point = connection.execute(
                text("SELECT id FROM grammar_point WHERE key = :key"), {"key": key}
            ).mappings().one_or_none()
            if point is None:
                return None
            connection.execute(
                text(
                    """INSERT INTO grammar_encounter (point_id, status, first_source, note)
                       VALUES (:point_id, :status, :source, :note)
                       ON CONFLICT (point_id) DO UPDATE SET
                         status = CASE
                             WHEN grammar_encounter.status = 'understood' THEN grammar_encounter.status
                             ELSE EXCLUDED.status
                         END,
                         note = COALESCE(EXCLUDED.note, grammar_encounter.note)"""
                ),
                {"point_id": point["id"], "status": status, "source": source, "note": note},
            )
        return self.get_grammar_point(key)

    def save_grammar_explanation(self, key: str, content: str) -> None:
        with self.engine.begin() as connection:
            point = connection.execute(
                text("SELECT id FROM grammar_point WHERE key = :key"), {"key": key}
            ).mappings().one_or_none()
            if point is None:
                return
            connection.execute(
                text(
                    """INSERT INTO grammar_explanation (point_id, content)
                       VALUES (:point_id, :content)
                       ON CONFLICT (point_id) DO UPDATE SET content = EXCLUDED.content"""
                ),
                {"point_id": point["id"], "content": content},
            )

    def corrections_touching(self, key: str, limit: int = 3) -> list[dict[str, Any]]:
        """The learner's own mistakes on this point, so §12.3 can open with their
        sentence instead of an invented example."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT ci.original_fragment, ci.replacement, ci.reason_zh
                       FROM chat_correction_item ci
                       WHERE ci.grammar_key = :key
                       ORDER BY ci.id DESC LIMIT :limit"""
                ),
                {"key": key, "limit": limit},
            ).mappings().all()
        return [dict(row) for row in rows]

    # ── vocabulary ──────────────────────────────────────────────

    @staticmethod
    def _vocabulary_row(row: Any) -> dict[str, Any]:
        data = dict(row)
        for key in ("created_at", "next_review_at"):
            value = data.get(key)
            if hasattr(value, "isoformat"):
                data[key] = value.isoformat()
        return data

    def add_vocabulary(
        self,
        *,
        word: str,
        reading: str | None,
        meaning: str,
        part_of_speech: str | None,
        context: str | None,
        example_ja: str | None = None,
        example_zh: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Save a word, or fold the save into the existing entry for the same word.

        Re-saving a word already in the table only fills in fields that are still
        blank (an entry stored before example sentences existed can pick one up)
        and never touches review progress — looking a word up again should not
        demote a word already worked up to a higher Leitner box.

        Returns (row, already_saved).
        """
        params = {
            "word": word.strip(),
            "reading": reading,
            "meaning": meaning.strip(),
            "part_of_speech": part_of_speech,
            "context": context,
            "example_ja": example_ja,
            "example_zh": example_zh,
        }
        with self.engine.begin() as connection:
            existing = connection.execute(
                text("SELECT id FROM vocabulary WHERE word = :word ORDER BY id LIMIT 1"),
                {"word": params["word"]},
            ).mappings().one_or_none()
            if existing is not None:
                row = connection.execute(
                    text(
                        """UPDATE vocabulary SET
                             reading        = COALESCE(reading, :reading),
                             part_of_speech = COALESCE(part_of_speech, :part_of_speech),
                             context        = COALESCE(context, :context),
                             example_ja     = COALESCE(example_ja, :example_ja),
                             example_zh     = COALESCE(example_zh, :example_zh)
                           WHERE id = :id
                           RETURNING *"""
                    ),
                    {**params, "id": existing["id"]},
                ).mappings().one()
                return self._vocabulary_row(row), True
            row = connection.execute(
                text(
                    """INSERT INTO vocabulary
                        (word, reading, meaning, part_of_speech, context, example_ja, example_zh)
                     VALUES (:word, :reading, :meaning, :part_of_speech, :context, :example_ja, :example_zh)
                     RETURNING *"""
                ),
                params,
            ).mappings().one()
        return self._vocabulary_row(row), False

    def list_vocabulary(self, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT * FROM vocabulary ORDER BY created_at DESC, id DESC "
                    "LIMIT :limit OFFSET :offset"
                ),
                {"limit": limit, "offset": offset},
            ).mappings().all()
        return [self._vocabulary_row(row) for row in rows]

    def delete_vocabulary(self, vocabulary_id: int) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM vocabulary WHERE id = :id"), {"id": vocabulary_id}
            )
        return result.rowcount > 0

    # Leitner-style spaced repetition: correct answers push the word into a
    # higher box (longer gap before it's due again); a miss drops it back to
    # box 1 so it resurfaces soon.
    _REVIEW_INTERVALS: dict[int, timedelta] = {
        1: timedelta(minutes=10),
        2: timedelta(days=1),
        3: timedelta(days=3),
        4: timedelta(days=7),
        5: timedelta(days=14),
        6: timedelta(days=30),
    }

    def list_due_vocabulary(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT * FROM vocabulary WHERE next_review_at <= now()
                     ORDER BY next_review_at ASC, id ASC LIMIT :limit"""
                ),
                {"limit": limit},
            ).mappings().all()
        return [self._vocabulary_row(row) for row in rows]

    def record_vocabulary_review(self, vocabulary_id: int, *, correct: bool) -> dict[str, Any] | None:
        with self.engine.begin() as connection:
            current = connection.execute(
                text("SELECT box FROM vocabulary WHERE id = :id"), {"id": vocabulary_id}
            ).mappings().one_or_none()
            if current is None:
                return None
            new_box = min(int(current["box"]) + 1, 6) if correct else 1
            next_review_at = datetime.now(UTC) + self._REVIEW_INTERVALS[new_box]
            row = connection.execute(
                text(
                    """UPDATE vocabulary
                       SET box = :box, review_count = review_count + 1, next_review_at = :next_review_at
                       WHERE id = :id
                       RETURNING *"""
                ),
                {"box": new_box, "next_review_at": next_review_at, "id": vocabulary_id},
            ).mappings().one()
        return self._vocabulary_row(row)
