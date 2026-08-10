from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from .grammar_catalogue import catalogue_rows
from .learning_events import LEARNING_EVENT_SCHEMA_VERSION, validated_learning_event_payload
from .text import canonical_source_key

logger = logging.getLogger(__name__)

# §5.11: JLPT levels from most to least basic. Learning state may change prompt
# ordering, but it must never hide an unseen point from recurrence detection.
GRAMMAR_LEVEL_ORDER = ("N5", "N4", "N3", "N2", "N1")

# §5.13: background decision records. Traces are diagnostics, not facts, so they
# expire; the learning history they describe stays in the source tables.
DECISION_TRACE_SCHEMA_VERSION = "decision-trace-v1"
DECISION_TRACE_RETENTION_DAYS = 30

# §14.2: how many entries the journal page shows and the model gets as context. Bounded
# so that opening it, and answering in it, never gets slower as the history grows (§5.17).
JOURNAL_TIMELINE_LIMIT = 20

# §5.18: what counts as "you stopped in the middle" rather than "you finished" or "you
# opened it and backed out". Both numbers come from looking at the real database on
# 2026-08-10: three of four saved positions sat at 85–88% (finished — reminding you about
# those is just nagging) and one sat at 7% (actually interrupted). A 90% ceiling would
# have turned all three finished materials into reminders.
#
# The ratio is a filter and never leaves the repository: §4.2 says playback position
# expresses media resumption, not learning progress, so showing it as a percentage would
# be §1.4's banned progress bar under another name.
RESUME_MIN_RATIO = 0.02
RESUME_MAX_RATIO = 0.80


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

    def _record_decision_trace(
        self,
        *,
        call_source: str,
        status: str,
        reason: str,
        duration_ms: int,
        failure_stage: str | None = None,
        rule_version: str | None = None,
        subject_kind: str | None = None,
        subject_key: str | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
        evidence_refs: list[Any] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Record what a background enhancement path just did (§5.13).

        Swallows its own failures on purpose: observability must never become a new
        way for the thing it observes to break. A disk hiccup here should cost a
        diagnostic row, not turn "the memory rebuild failed but chat was fine" into
        "chat failed too". Written in its own transaction for the same reason.

        `reason` and `detail` carry metadata only — never the learner's own text.
        Follow `evidence_refs` back to the source tables when the original wording
        is needed; copying it here would create a second place to protect and
        delete, and this table has no deletion trigger following the sources.
        """
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        """INSERT INTO decision_trace
                           (schema_version, call_source, status, failure_stage, reason,
                            rule_version, subject_kind, subject_key, model_provider,
                            model_name, prompt_version, evidence_refs, duration_ms, detail)
                           VALUES (:schema_version, :call_source, :status, :failure_stage,
                                   :reason, :rule_version, :subject_kind, :subject_key,
                                   :model_provider, :model_name, :prompt_version,
                                   CAST(:evidence_refs AS JSONB), :duration_ms,
                                   CAST(:detail AS JSONB))"""
                    ),
                    {
                        "schema_version": DECISION_TRACE_SCHEMA_VERSION,
                        "call_source": call_source,
                        "status": status,
                        "failure_stage": failure_stage,
                        "reason": reason,
                        "rule_version": rule_version,
                        "subject_kind": subject_kind,
                        "subject_key": subject_key,
                        "model_provider": model_provider,
                        "model_name": model_name,
                        "prompt_version": prompt_version,
                        "evidence_refs": json.dumps(evidence_refs or [], ensure_ascii=False),
                        "duration_ms": duration_ms,
                        "detail": json.dumps(detail or {}, ensure_ascii=False),
                    },
                )
        except Exception:
            logger.exception("Failed to record decision trace", extra={"call_source": call_source})

    def _record_event_with_trace(
        self,
        *,
        call_source: str,
        subject_kind: str,
        subject_key: str,
        source_id: int,
        event: dict[str, Any],
    ) -> None:
        """Index one adapter's event, best-effort, and say so in the trace (§5.13).

        The single-event adapters (saved word, review attempt, finished shadowing)
        all share this shape: the source fact is already committed, so a failure
        here costs the index entry and nothing else.
        """
        started = time.perf_counter()
        try:
            self._record_learning_event(**event)
        except Exception:
            logger.exception(f"Failed to record {event['kind']} learning event", extra={"source_id": source_id})
            self._record_decision_trace(
                call_source=call_source,
                status="failed",
                failure_stage="insert_event",
                reason=f"{event['kind']} 事件写入失败，来源行已提交且不受影响",
                rule_version=LEARNING_EVENT_SCHEMA_VERSION,
                subject_kind=subject_kind,
                subject_key=subject_key,
                evidence_refs=[source_id],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return
        self._record_decision_trace(
            call_source=call_source,
            status="ok",
            reason=f"已索引 {event['kind']} 事件",
            rule_version=LEARNING_EVENT_SCHEMA_VERSION,
            subject_kind=subject_kind,
            subject_key=subject_key,
            evidence_refs=[source_id],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def list_decision_traces(
        self,
        *,
        call_source: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        parameters: dict[str, Any] = {"limit": limit}
        if call_source is not None:
            conditions.append("call_source = :call_source")
            parameters["call_source"] = call_source
        if status is not None:
            conditions.append("status = :status")
            parameters["status"] = status
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""SELECT * FROM decision_trace {where}
                        ORDER BY created_at DESC, id DESC LIMIT :limit"""
                ),
                parameters,
            ).mappings().all()
        return [dict(row) for row in rows]

    def prune_decision_traces(self, *, retention_days: int = DECISION_TRACE_RETENTION_DAYS) -> int:
        """Diagnostics are not facts: every real learning fact lives in the source
        tables and `learning_event`, so dropping old traces loses no history."""
        with self.engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM decision_trace WHERE created_at < now() - make_interval(days => :days)"),
                {"days": retention_days},
            )
        return result.rowcount

    def _record_learning_event(
        self,
        *,
        kind: str,
        source_table: str,
        source_id: int,
        subject_key: str,
        occurred_at: Any,
        payload: dict[str, Any],
        subject_kind: str = "grammar_point",
        confidence: float | None = None,
    ) -> bool:
        """Write one validated v1 event in its own transaction.

        Callers invoke this only after the source fact has committed. A malformed
        event or event-index failure therefore cannot roll back chat, companion,
        vocabulary or shadowing content, and the source tables remain sufficient
        for idempotent replay.
        """

        validated_payload = validated_learning_event_payload(kind, payload)
        with self.engine.begin() as connection:
            inserted = connection.execute(
                text(
                    """INSERT INTO learning_event
                       (schema_version, kind, source_table, source_id, subject_kind,
                        subject_key, confidence, occurred_at, payload)
                       VALUES (:schema_version, :kind, :source_table, :source_id,
                               :subject_kind, :subject_key, :confidence, :occurred_at,
                               CAST(:payload AS JSONB))
                       ON CONFLICT (source_table, source_id, subject_kind, subject_key)
                       DO NOTHING RETURNING id"""
                ),
                {
                    "schema_version": LEARNING_EVENT_SCHEMA_VERSION,
                    "kind": kind,
                    "source_table": source_table,
                    "source_id": source_id,
                    "subject_kind": subject_kind,
                    "subject_key": subject_key,
                    "confidence": confidence,
                    "occurred_at": occurred_at,
                    "payload": json.dumps(validated_payload, ensure_ascii=False),
                },
            ).scalar_one_or_none()
        return inserted is not None

    def backfill_learning_events(self) -> list[str]:
        """Replay legacy grammar links, saved words and completed shadowing attempts
        into the v1 event envelope, idempotently.

        `apply_schema` creates the destination table first; startup then calls this
        method before serving requests. Newly inserted keys and active events whose
        projection is missing are repaired; a healthy repeat startup is a no-op.

        Reviews before `vocabulary_review_attempt` existed have no recoverable event
        and must not be fabricated from aggregate `review_count`. Every attempt row
        that does exist is one real post-migration fact and is replayed normally,
        together with saved words and completed shadowing attempts.
        """

        started = time.perf_counter()
        with self.engine.begin() as connection:
            correction_keys = connection.execute(
                text(
                    """INSERT INTO learning_event
                       (schema_version, kind, source_table, source_id, subject_kind,
                        subject_key, actor, confidence, occurred_at, backfilled, payload)
                       SELECT :schema_version, 'correction_item', 'chat_correction_item',
                              ci.id, 'grammar_point', ci.grammar_key, 'user', NULL,
                              c.created_at, true,
                              jsonb_build_object(
                                  'original', ci.original_fragment,
                                  'replacement', ci.replacement,
                                  'reason_zh', ci.reason_zh,
                                  'category', ci.category
                              )
                       FROM chat_correction_item ci
                       JOIN chat_correction c ON c.id = ci.correction_id
                       JOIN grammar_point p ON p.key = ci.grammar_key
                       WHERE ci.grammar_key IS NOT NULL
                       ON CONFLICT (source_table, source_id, subject_kind, subject_key)
                       DO NOTHING RETURNING subject_key"""
                ),
                {"schema_version": LEARNING_EVENT_SCHEMA_VERSION},
            ).scalars().all()
            # The category subject exists for every correction, including the ones the
            # model could not tie to a grammar point (§5.11); without this the fact
            # layer would only remember grammar-shaped mistakes.
            connection.execute(
                text(
                    """INSERT INTO learning_event
                       (schema_version, kind, source_table, source_id, subject_kind,
                        subject_key, actor, confidence, occurred_at, backfilled, payload)
                       SELECT :schema_version, 'correction_item', 'chat_correction_item',
                              ci.id, 'correction_category', ci.category, 'user', NULL,
                              c.created_at, true,
                              jsonb_build_object(
                                  'original', ci.original_fragment,
                                  'replacement', ci.replacement,
                                  'reason_zh', ci.reason_zh,
                                  'category', ci.category
                              )
                       FROM chat_correction_item ci
                       JOIN chat_correction c ON c.id = ci.correction_id
                       ON CONFLICT (source_table, source_id, subject_kind, subject_key)
                       DO NOTHING"""
                ),
                {"schema_version": LEARNING_EVENT_SCHEMA_VERSION},
            )
            # Reviews that predate vocabulary_review_attempt cannot be reconstructed
            # from vocabulary.review_count. Every row that does exist in the immutable
            # attempt table is real, though, and must repair a failed event write.
            connection.execute(
                text(
                    """INSERT INTO learning_event
                       (schema_version, kind, source_table, source_id, subject_kind,
                        subject_key, actor, confidence, occurred_at, backfilled, payload)
                       SELECT :schema_version, 'vocabulary_reviewed', 'vocabulary_review_attempt',
                              vra.id, 'vocabulary_word', vra.vocabulary_id::text, 'user', NULL,
                              vra.created_at, true,
                              jsonb_build_object(
                                  'correct', vra.correct,
                                  'box_before', vra.box_before,
                                  'box_after', vra.box_after
                              )
                       FROM vocabulary_review_attempt vra
                       ON CONFLICT (source_table, source_id, subject_kind, subject_key)
                       DO NOTHING"""
                ),
                {"schema_version": LEARNING_EVENT_SCHEMA_VERSION},
            )
            companion_keys = connection.execute(
                text(
                    """INSERT INTO learning_event
                       (schema_version, kind, source_table, source_id, subject_kind,
                        subject_key, actor, confidence, occurred_at, backfilled, payload)
                       SELECT :schema_version, 'companion_question', 'companion_message',
                              cm.id, 'grammar_point', p.key, 'user', NULL,
                              cm.created_at, true,
                              jsonb_build_object(
                                  'question', cm.content,
                                  'material_id', cm.material_id,
                                  'segment_id', cm.segment_id
                              )
                       FROM companion_grammar_evidence cge
                       JOIN companion_message cm ON cm.id = cge.message_id
                       JOIN grammar_point p ON p.id = cge.point_id
                       ON CONFLICT (source_table, source_id, subject_kind, subject_key)
                       DO NOTHING RETURNING subject_key"""
                ),
                {"schema_version": LEARNING_EVENT_SCHEMA_VERSION},
            ).scalars().all()
            connection.execute(
                text(
                    """INSERT INTO learning_event
                       (schema_version, kind, source_table, source_id, subject_kind,
                        subject_key, actor, confidence, occurred_at, backfilled, payload)
                       SELECT :schema_version, 'vocabulary_saved', 'vocabulary', v.id,
                              'vocabulary_word', v.id::text, 'user', NULL, v.created_at, true,
                              jsonb_build_object('word', v.word, 'reading', v.reading, 'meaning', v.meaning)
                       FROM vocabulary v
                       ON CONFLICT (source_table, source_id, subject_kind, subject_key)
                       DO NOTHING"""
                ),
                {"schema_version": LEARNING_EVENT_SCHEMA_VERSION},
            )
            connection.execute(
                text(
                    """INSERT INTO learning_event
                       (schema_version, kind, source_table, source_id, subject_kind,
                        subject_key, actor, confidence, occurred_at, backfilled, payload)
                       SELECT :schema_version, 'shadowing_completed', 'shadowing_attempt', sa.id,
                              'segment', sa.segment_id::text, 'user', NULL, sa.created_at, true,
                              jsonb_build_object('score', sa.score)
                       FROM shadowing_attempt sa
                       WHERE sa.status = 'ready'
                       ON CONFLICT (source_table, source_id, subject_kind, subject_key)
                       DO NOTHING"""
                ),
                {"schema_version": LEARNING_EVENT_SCHEMA_VERSION},
            )
            missing_projection_keys = connection.execute(
                text(
                    """SELECT DISTINCT le.subject_key
                       FROM learning_event le
                       JOIN grammar_point p ON p.key = le.subject_key
                       LEFT JOIN grammar_encounter e ON e.point_id = p.id
                       WHERE le.schema_version = :schema_version
                         AND le.subject_kind = 'grammar_point'
                         AND le.rejected_at IS NULL
                         AND e.point_id IS NULL"""
                ),
                {"schema_version": LEARNING_EVENT_SCHEMA_VERSION},
            ).scalars().all()
        keys = list(
            dict.fromkeys(
                str(key) for key in [*correction_keys, *companion_keys, *missing_projection_keys]
            )
        )
        for key in keys:
            self.reconcile_grammar_projection(key)
        # Memories are derived from the events this backfill just repaired, so the
        # rebuild belongs here too — quietly, since a missing memory must not stop
        # the service from starting the way a missing event index would.
        # Startup is the natural place to expire diagnostics (§5.13): traces describe
        # history, they are not history, so dropping old ones loses no learning fact.
        pruned = self.prune_decision_traces()
        self._record_decision_trace(
            call_source="learning_event_backfill",
            status="ok",
            reason=f"回填后需重算投影的主体 {len(keys)} 个，裁剪过期 trace {pruned} 行",
            rule_version=LEARNING_EVENT_SCHEMA_VERSION,
            duration_ms=int((time.perf_counter() - started) * 1000),
            detail={"reconciled": len(keys), "pruned_traces": pruned},
        )
        return keys

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
        collection_id: int | None = None,
        include_collection_sections: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """`collection_id` narrows to one collection's sections and orders them by section
        number instead of by date (§15.5).

        Sharing this query rather than writing a second one for collections is deliberate:
        it carries four lateral joins that the client depends on (delivery keys, current
        job, thumbnail), and two copies would drift apart the first time one is touched.
        """

        conditions: list[str] = []
        parameters: dict[str, Any] = {"offset": offset}
        if status:
            conditions.append("m.status = :status")
            parameters["status"] = status
        if collection_id is not None:
            conditions.append("m.collection_id = :collection_id")
            parameters["collection_id"] = collection_id
        elif not include_collection_sections:
            # §15.5: a section is reached through its collection. Leaving it in the loose
            # library too showed every section twice and undid the grouping.
            conditions.append("m.collection_id IS NULL")
        where_clause = " AND ".join(conditions) if conditions else "true"
        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT :limit"
            parameters["limit"] = limit
        order_clause = (
            "m.collection_index, m.id"
            if collection_id is not None
            else "m.created_at DESC, m.id DESC"
        )
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
                    ORDER BY {order_clause}
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
        """Counts what the library actually lists, so the header cannot disagree with it —
        sections inside a collection are excluded here for the same reason (§15.5)."""

        conditions: list[str] = ["collection_id IS NULL"]
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

    def add_companion_message(
        self,
        material_id: int,
        segment_id: int | None,
        role: str,
        content: str,
        lens: str | None = None,
    ) -> dict[str, Any]:
        """`lens` is the §5.15 reading angle; NULL means a freely typed question."""

        with self.engine.begin() as connection:
            row = connection.execute(
                text("""INSERT INTO companion_message (material_id, segment_id, role, content, lens)
                VALUES (:material_id, :segment_id, :role, :content, :lens) RETURNING *"""),
                {
                    "material_id": material_id,
                    "segment_id": segment_id,
                    "role": role,
                    "content": content,
                    "lens": lens,
                },
            ).mappings().one()
        return dict(row)

    def companion_messages(
        self,
        material_id: int,
        limit: int = 40,
        *,
        segment_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Most recent turns, oldest first for display.

        This used to return every message a material had ever accumulated. Nothing
        reads the older ones — the model prompt takes the last 12 and the sheet only
        scrolls back a little — but the client paid for all of them on every open,
        including one furigana request per Japanese run in each.

        `segment_id` narrows it to one sentence (§5.17, 2026-08-10). With it, opening the
        sheet costs what that sentence has accumulated instead of what the whole material
        has — which is what §5.17's rule ("the cost of opening must not depend on history
        length") actually asks for. A cap of 40 bounded it; it did not make it independent.
        """

        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    # The cast is required, not stylistic: with segment_id = None Postgres
                    # cannot infer a type for the bare placeholder in `IS NULL` and the
                    # query fails outright. Found by opening the app, not by the tests —
                    # the no-filter path had no integration coverage, which it now has.
                    """SELECT * FROM (
                           SELECT * FROM companion_message
                           WHERE material_id = :material_id
                             AND (CAST(:segment_id AS BIGINT) IS NULL
                                  OR segment_id = CAST(:segment_id AS BIGINT))
                           ORDER BY id DESC LIMIT :limit
                       ) recent ORDER BY id"""
                ),
                {"material_id": material_id, "limit": limit, "segment_id": segment_id},
            ).mappings().all()
        return [dict(row) for row in rows]

    def delete_companion_message(self, message_id: int) -> bool:
        """Used to drop a standalone question whose answer never arrived (§5.16)."""

        with self.engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM companion_message WHERE id = :id"), {"id": message_id}
            )
        return result.rowcount > 0

    def standalone_ask_messages(self, limit: int = 40) -> list[dict[str, Any]]:
        """§5.16: questions asked on their own, oldest first for display."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT * FROM (
                           SELECT * FROM companion_message WHERE material_id IS NULL
                           ORDER BY id DESC LIMIT :limit
                       ) recent ORDER BY id"""
                ),
                {"limit": limit},
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
        touched_keys: list[str] = []
        with self.engine.begin() as connection:
            touched_keys = [
                str(value)
                for value in connection.execute(
                    text(
                        """SELECT DISTINCT ci.grammar_key
                           FROM chat_correction_item ci
                           JOIN chat_correction c ON c.id = ci.correction_id
                           WHERE c.session_id = :session_id AND ci.grammar_key IS NOT NULL"""
                    ),
                    {"session_id": session_id},
                ).scalars()
            ]
            # learning_event has no FK to chat_correction_item (§5.11: a logical
            # reference, not a physical one), so the cascade below would otherwise
            # leave orphaned evidence that keeps counting after the session is gone.
            connection.execute(
                text(
                    """DELETE FROM learning_event
                       WHERE source_table = 'chat_correction_item'
                         AND source_id IN (
                             SELECT ci.id FROM chat_correction_item ci
                             JOIN chat_correction c ON c.id = ci.correction_id
                             WHERE c.session_id = :session_id
                         )"""
                ),
                {"session_id": session_id},
            )
            deleted = connection.execute(
                text("DELETE FROM chat_session WHERE id = :session_id RETURNING id"),
                {"session_id": session_id},
            ).scalar_one_or_none()
        if deleted is not None:
            for key in touched_keys:
                self.reconcile_grammar_projection(key)
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
        decision_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
        pending_learning_events: list[dict[str, Any]] = []
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
                            (correction_id, idx, original_fragment, replacement,
                             same_register_replacement, reason_zh, category, grammar_key)
                            VALUES (:correction_id, :idx, :original, :replacement,
                                    :same_register_replacement, :reason_zh, :category, :grammar_key)
                            RETURNING id, correction_id, idx, original_fragment AS original,
                                replacement, same_register_replacement, reason_zh, category,
                                grammar_key"""
                        ),
                        # Bound explicitly rather than splatting the item dict: the dict
                        # now carries a field the statement has to name, and a silent
                        # mismatch between the two is exactly the kind of thing a splat
                        # hides.
                        {
                            "correction_id": int(correction_row["id"]),
                            "idx": index,
                            "original": item["original"],
                            "replacement": item["replacement"],
                            "same_register_replacement": item.get("same_register_replacement"),
                            "reason_zh": item["reason_zh"],
                            "category": item["category"],
                            "grammar_key": item.get("grammar_key"),
                        },
                    ).mappings().one()
                    items.append(dict(stored_item))
                    payload = {
                        "original": stored_item["original"],
                        "replacement": stored_item["replacement"],
                        "reason_zh": stored_item["reason_zh"],
                        "category": stored_item["category"],
                    }
                    # Every correction is a fact worth indexing, whether or not the
                    # model could pin it to a grammar point (§5.11): word-choice and
                    # naturalness corrections almost never carry a grammar_key, and
                    # gating the event on one would leave the fact layer remembering
                    # only the mistakes that happen to fit the grammar skeleton.
                    pending_learning_events.append(
                        {
                            "kind": "correction_item",
                            "source_table": "chat_correction_item",
                            "source_id": int(stored_item["id"]),
                            "subject_kind": "correction_category",
                            "subject_key": str(stored_item["category"]),
                            "occurred_at": correction_row["created_at"],
                            "payload": payload,
                        }
                    )
                    # A real mistake is the main path into the grammar skeleton (§12.1).
                    if key := item.get("grammar_key"):
                        pending_learning_events.append(
                            {
                                "kind": "correction_item",
                                "source_table": "chat_correction_item",
                                "source_id": int(stored_item["id"]),
                                "subject_kind": "grammar_point",
                                "subject_key": str(key),
                                "occurred_at": correction_row["created_at"],
                                "payload": payload,
                            }
                        )
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
        # Event indexing, projection and memory are enhancements. They run only after
        # the chat transaction commits and cannot make a successful turn look failed.
        # Which is exactly why they leave a trace (§5.13): silent best-effort work
        # otherwise gives nobody a way to ask why a point never registered.
        if pending_learning_events:
            started = time.perf_counter()
            indexed = 0
            failure_stage: str | None = None
            for event in pending_learning_events:
                try:
                    self._record_learning_event(**event)
                except Exception:
                    logger.exception(
                        "Failed to record correction learning event",
                        extra={"source_id": event["source_id"], "subject_key": event["subject_key"]},
                    )
                    failure_stage = failure_stage or "insert_event"
                    continue
                indexed += 1
                # Only the grammar association feeds the grammar skeleton; the
                # category event exists for the fact layer and has no projection.
                if event["subject_kind"] != "grammar_point":
                    continue
                try:
                    self.mark_grammar_encounter(
                        str(event["subject_key"]),
                        status="encountered",
                        source="correction",
                        note=str(event["payload"]["original"]),
                        invalidate_explanation=True,
                    )
                except Exception:
                    logger.exception(
                        "Failed to project correction onto the grammar skeleton",
                        extra={"subject_key": event["subject_key"]},
                    )
                    failure_stage = failure_stage or "project_grammar"
            self._record_decision_trace(
                call_source="chat_correction_index",
                status="failed" if failure_stage else "ok",
                failure_stage=failure_stage,
                reason=f"索引 {indexed}/{len(pending_learning_events)} 条纠错事件",
                rule_version=LEARNING_EVENT_SCHEMA_VERSION,
                evidence_refs=[int(event["source_id"]) for event in pending_learning_events],
                duration_ms=int((time.perf_counter() - started) * 1000),
                model_provider=(decision_context or {}).get("model_provider"),
                model_name=(decision_context or {}).get("model_name"),
                prompt_version=(decision_context or {}).get("prompt_version"),
                detail={
                    "indexed": indexed,
                    "expected": len(pending_learning_events),
                    "attempted_providers": (decision_context or {}).get("attempted_providers", []),
                },
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
                            replacement, same_register_replacement, reason_zh, category
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
        touched_keys: list[str] = []
        with self.engine.begin() as connection:
            touched_keys = [
                str(value)
                for value in connection.execute(
                    text(
                        """SELECT DISTINCT grammar_key FROM chat_correction_item
                           WHERE correction_id = :correction_id AND grammar_key IS NOT NULL"""
                    ),
                    {"correction_id": correction_id},
                ).scalars()
            ]
            # Same reasoning as delete_chat_session: learning_event must be cleaned up
            # by hand since it only references chat_correction_item logically.
            connection.execute(
                text(
                    """DELETE FROM learning_event
                       WHERE source_table = 'chat_correction_item'
                         AND source_id IN (
                             SELECT id FROM chat_correction_item WHERE correction_id = :correction_id
                         )"""
                ),
                {"correction_id": correction_id},
            )
            deleted = connection.execute(
                text("DELETE FROM chat_correction WHERE id = :correction_id RETURNING id"),
                {"correction_id": correction_id},
            ).scalar_one_or_none()
        if deleted is not None:
            for key in touched_keys:
                self.reconcile_grammar_projection(key)
        return deleted is not None

    # ── learner memory (§5.12) ──────────────────────────────────

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
            attempt = connection.execute(
                text("""UPDATE shadowing_attempt SET asr_text = :transcript,
                    diff_json = CAST(:diff AS JSONB), score = :score, status = 'ready', error_message = NULL
                    WHERE id = :attempt_id
                    RETURNING segment_id, created_at"""),
                {"attempt_id": attempt_id, "transcript": transcript, "diff": json.dumps(diff, ensure_ascii=False),
                 "score": score},
            ).mappings().one()
        # §5.11: occurred_at is when the recording was submitted (this row's own
        # created_at), not when scoring finished — grading is an async job, and its
        # queue latency is not when the learning action itself happened. asr_text and
        # audio_path never enter the payload: only the derived score does, so the
        # event never duplicates a recording or its full private transcript.
        self._record_event_with_trace(
            call_source="shadowing_completed_index",
            subject_kind="segment",
            subject_key=str(attempt["segment_id"]),
            source_id=attempt_id,
            event={
                "kind": "shadowing_completed",
                "source_table": "shadowing_attempt",
                "source_id": attempt_id,
                "subject_kind": "segment",
                "subject_key": str(attempt["segment_id"]),
                "occurred_at": attempt["created_at"],
                "payload": {"score": score},
            },
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

    def mark_material_failed(self, material_id: int, message: str) -> None:
        """One section of a split failed (§15.2).

        The job-level failure path marks the job's own `material_id`, but a `split_video`
        job produces many materials and belongs to none of them — so a failed section has
        to be marked here, individually, leaving its siblings usable.
        """

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """UPDATE material SET status = 'failed', error_message = :message
                       WHERE id = :material_id"""
                ),
                {"message": message[:2_000], "material_id": material_id},
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

    def grammar_catalogue_for_prompt(self) -> list[tuple[str, str, str, str, str]]:
        """Build the compact prompt catalogue without creating discovery blind spots.

        Current catalogue size is small enough to include every key. Existing
        encounters move first so the model sees personal history prominently, but
        an unseen N4/N3 point remains available for a first real mistake. Any future
        retrieval-based limit must first prove recall against this complete baseline.
        """
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT p.key, p.title_ja, p.title_zh, p.level, p.category,
                              p.sort_order, p.id, (e.point_id IS NOT NULL) AS encountered
                       FROM grammar_point p
                       LEFT JOIN grammar_encounter e ON e.point_id = p.id"""
                )
            ).mappings().all()
        # Level as TEXT sorts lexically ("N1" < "N5"), the wrong way round for JLPT.
        # State changes ordering only; it never excludes a catalogue entry.
        level_rank = {level: index for index, level in enumerate(GRAMMAR_LEVEL_ORDER)}
        rows = sorted(
            (dict(row) for row in rows),
            key=lambda row: (
                0 if row["encountered"] else 1,
                level_rank.get(str(row["level"]), len(GRAMMAR_LEVEL_ORDER)),
                row["sort_order"],
                row["id"],
            ),
        )
        return [(row["key"], row["title_ja"], row["title_zh"], row["level"], row["category"]) for row in rows]

    def _grammar_rows(self, key: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE p.key = :key" if key is not None else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""SELECT p.id, p.key, p.title_ja, p.title_zh, p.level, p.category, p.sort_order,
                               e.status, e.status_source, e.first_source, e.last_source, e.note,
                               e.last_evidence_at, e.browsed_at, e.status_changed_at,
                               e.created_at AS encountered_at,
                               e.updated_at,
                               x.content AS explanation,
                               x.prompt_version AS explanation_prompt_version,
                               x.evidence_fingerprint AS explanation_evidence_fingerprint,
                               x.evidence_refs AS explanation_evidence_refs,
                               x.updated_at AS explanation_updated_at,
                               COALESCE(m.mistake_count, 0) AS mistake_count,
                               m.latest_mistake, m.latest_mistake_at,
                               COALESCE(q.question_count, 0) AS companion_question_count,
                               q.latest_question, q.latest_question_at
                        FROM grammar_point p
                        LEFT JOIN grammar_encounter e ON e.point_id = p.id
                        LEFT JOIN grammar_explanation x ON x.point_id = p.id
                        LEFT JOIN LATERAL (
                            SELECT count(*)::int AS mistake_count,
                                   (array_agg(le.payload->>'original'
                                        ORDER BY le.occurred_at DESC, le.id DESC))[1] AS latest_mistake,
                                   max(le.occurred_at) AS latest_mistake_at
                            FROM learning_event le
                            WHERE le.subject_kind = 'grammar_point' AND le.subject_key = p.key
                              AND le.schema_version = :schema_version
                              AND le.kind = 'correction_item' AND le.rejected_at IS NULL
                        ) m ON TRUE
                        LEFT JOIN LATERAL (
                            SELECT count(*)::int AS question_count,
                                   (array_agg(le.payload->>'question'
                                        ORDER BY le.occurred_at DESC, le.id DESC))[1] AS latest_question,
                                   max(le.occurred_at) AS latest_question_at
                            FROM learning_event le
                            WHERE le.subject_kind = 'grammar_point' AND le.subject_key = p.key
                              AND le.schema_version = :schema_version
                              AND le.kind = 'companion_question' AND le.rejected_at IS NULL
                        ) q ON TRUE
                        {where}
                        ORDER BY p.level, p.sort_order, p.id"""
                ),
                {
                    "schema_version": LEARNING_EVENT_SCHEMA_VERSION,
                    **({"key": key} if key is not None else {}),
                },
            ).mappings().all()
        return [self._grammar_row(dict(row)) for row in rows]

    @staticmethod
    def _grammar_row(data: dict[str, Any]) -> dict[str, Any]:
        mistake_count = int(data.get("mistake_count") or 0)
        question_count = int(data.get("companion_question_count") or 0)
        data["mistake_count"] = mistake_count
        data["companion_question_count"] = question_count
        data["has_mistake"] = mistake_count > 0
        data["has_companion_question"] = question_count > 0
        data["has_explanation"] = bool(data.get("explanation"))

        evidence: list[tuple[Any, str]] = []
        if data.get("latest_mistake_at") is not None:
            evidence.append((data["latest_mistake_at"], "correction"))
        if data.get("latest_question_at") is not None:
            evidence.append((data["latest_question_at"], "companion"))
        evidence.sort(key=lambda item: item[0], reverse=True)
        latest_evidence_at = evidence[0][0] if evidence else None
        latest_evidence_source = evidence[0][1] if evidence else None
        data["latest_learning_evidence_at"] = latest_evidence_at
        data["latest_learning_evidence_source"] = latest_evidence_source

        status = data.get("status")
        status_changed_at = data.get("status_changed_at")
        needs_attention = status == "encountered"
        if status == "understood" and latest_evidence_at is not None and status_changed_at is not None:
            needs_attention = latest_evidence_at > status_changed_at
        data["needs_attention"] = needs_attention

        if status is None:
            reason = "还没有来自真实学习行为的记录。"
        elif status == "understood" and needs_attention:
            location = "聊天纠错" if latest_evidence_source == "correction" else "阅读陪读"
            reason = f"你曾标记为已弄懂，后来又在{location}中遇到了这个点。"
        elif status == "understood":
            reason = "你已将这个点标记为已弄懂。"
        elif data.get("status_source") == "manual":
            reason = "你已将这个点重新标记为需要留意。"
        elif data.get("last_source") == "correction" or mistake_count:
            reason = "因为你在聊天纠错中写错过这个点。"
        elif data.get("last_source") == "companion" or question_count:
            reason = "因为你在阅读陪读中主动问过这个点。"
        else:
            reason = "因为你主动打开过这条讲解。"
        data["state_reason"] = reason
        return data

    def list_grammar_points(self) -> list[dict[str, Any]]:
        """The skeleton is a projection: unresolved recent evidence comes first,
        then settled history, then untouched catalogue entries."""
        rows = self._grammar_rows()

        def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, float, int]:
            index, row = item
            if row["needs_attention"]:
                group = 0
            elif row.get("status") == "understood":
                group = 1
            else:
                group = 2
            value = row.get("latest_learning_evidence_at") or row.get("last_evidence_at")
            timestamp = value.timestamp() if hasattr(value, "timestamp") else 0.0
            return group, -timestamp, index

        return [row for _, row in sorted(enumerate(rows), key=sort_key)]

    def get_grammar_point(self, key: str) -> dict[str, Any] | None:
        rows = self._grammar_rows(key)
        return rows[0] if rows else None

    def mark_grammar_encounter(
        self,
        key: str,
        *,
        status: str,
        source: str | None = None,
        note: str | None = None,
        manual: bool = False,
        invalidate_explanation: bool = False,
    ) -> dict[str, Any] | None:
        """Records evidence or an explicit learner decision.

        Automatic evidence never downgrades an explicit understood state. A manual
        action may move either way, because the learner remains the authority on
        whether something currently needs attention.
        """
        with self.engine.begin() as connection:
            point_id = connection.execute(
                text("SELECT id FROM grammar_point WHERE key = :key"), {"key": key}
            ).scalar_one_or_none()
            if point_id is None:
                return None
            existing = connection.execute(
                text("SELECT * FROM grammar_encounter WHERE point_id = :point_id"),
                {"point_id": point_id},
            ).mappings().one_or_none()
            status_source = "manual" if manual else "automatic"
            if existing is None:
                connection.execute(
                    text(
                        """INSERT INTO grammar_encounter
                           (point_id, status, status_source, first_source, last_source, note, browsed_at)
                           VALUES (:point_id, :status, :status_source, :source, :source, :note,
                                   CASE WHEN :source = 'browse' THEN now() END)"""
                    ),
                    {
                        "point_id": point_id,
                        "status": status,
                        "status_source": status_source,
                        "source": source,
                        "note": note,
                    },
                )
            else:
                current_status = str(existing["status"])
                final_status = status if manual or current_status != "understood" else current_status
                final_status_source = status_source if manual else str(existing["status_source"])
                status_changed = manual or final_status != current_status
                connection.execute(
                    text(
                        """UPDATE grammar_encounter SET
                               status = :status,
                               status_source = :status_source,
                               last_source = COALESCE(:source, last_source),
                               note = COALESCE(:note, note),
                               last_evidence_at = CASE WHEN :source IS NOT NULL THEN now() ELSE last_evidence_at END,
                               browsed_at = CASE
                                   WHEN :source = 'browse' THEN COALESCE(browsed_at, now()) ELSE browsed_at
                               END,
                               status_changed_at = CASE
                                   WHEN :status_changed THEN now() ELSE status_changed_at
                               END
                           WHERE point_id = :point_id"""
                    ),
                    {
                        "point_id": point_id,
                        "status": final_status,
                        "status_source": final_status_source,
                        "source": source,
                        "note": note,
                        "status_changed": status_changed,
                    },
                )
            if invalidate_explanation:
                connection.execute(
                    text("DELETE FROM grammar_explanation WHERE point_id = :point_id"),
                    {"point_id": point_id},
                )
        return self.get_grammar_point(key)

    def record_companion_grammar_evidence(
        self,
        message_id: int,
        keys: list[str],
        *,
        decision_context: dict[str, Any] | None = None,
    ) -> list[str]:
        """Links an explicit learner question to known points, idempotently."""
        inserted_keys: list[str] = []
        message_data: dict[str, Any] | None = None
        with self.engine.begin() as connection:
            message = connection.execute(
                text(
                    """SELECT role, material_id, segment_id, content, created_at
                       FROM companion_message WHERE id = :message_id"""
                ),
                {"message_id": message_id},
            ).mappings().one_or_none()
            if message is None or message["role"] != "user":
                return []
            message_data = dict(message)
            for key in dict.fromkeys(keys):
                point_id = connection.execute(
                    text("SELECT id FROM grammar_point WHERE key = :key"), {"key": key}
                ).scalar_one_or_none()
                if point_id is None:
                    continue
                inserted = connection.execute(
                    text(
                        """INSERT INTO companion_grammar_evidence (message_id, point_id)
                           VALUES (:message_id, :point_id)
                           ON CONFLICT DO NOTHING RETURNING point_id"""
                    ),
                    {"message_id": message_id, "point_id": point_id},
                ).scalar_one_or_none()
                if inserted is not None:
                    inserted_keys.append(key)
        assert message_data is not None
        started = time.perf_counter()
        try:
            for key in inserted_keys:
                self._record_learning_event(
                    kind="companion_question",
                    source_table="companion_message",
                    source_id=message_id,
                    subject_key=key,
                    occurred_at=message_data["created_at"],
                    payload={
                        "question": message_data["content"],
                        "material_id": message_data["material_id"],
                        "segment_id": message_data["segment_id"],
                    },
                )
                self.mark_grammar_encounter(
                    key,
                    status="encountered",
                    source="companion",
                    invalidate_explanation=True,
                )
        except Exception:
            # The caller already treats this whole path as supplementary to the
            # teaching answer; the trace is so the gap is answerable afterwards.
            self._record_decision_trace(
                call_source="companion_grammar_index",
                status="failed",
                failure_stage="insert_event",
                reason="陪读语法证据登记失败，教学回答未受影响",
                rule_version=LEARNING_EVENT_SCHEMA_VERSION,
                subject_kind="grammar_point",
                model_provider=(decision_context or {}).get("model_provider"),
                model_name=(decision_context or {}).get("model_name"),
                prompt_version=(decision_context or {}).get("prompt_version"),
                evidence_refs=[message_id],
                duration_ms=int((time.perf_counter() - started) * 1000),
                detail={
                    "expected": len(inserted_keys),
                    "attempted_providers": (decision_context or {}).get("attempted_providers", []),
                },
            )
            raise
        if inserted_keys:
            self._record_decision_trace(
                call_source="companion_grammar_index",
                status="ok",
                reason=f"登记 {len(inserted_keys)} 个明确询问的语法点",
                rule_version=LEARNING_EVENT_SCHEMA_VERSION,
                subject_kind="grammar_point",
                model_provider=(decision_context or {}).get("model_provider"),
                model_name=(decision_context or {}).get("model_name"),
                prompt_version=(decision_context or {}).get("prompt_version"),
                evidence_refs=[message_id],
                duration_ms=int((time.perf_counter() - started) * 1000),
                detail={
                    "subject_keys": inserted_keys,
                    "attempted_providers": (decision_context or {}).get("attempted_providers", []),
                },
            )
        return inserted_keys

    def _set_learning_event_rejected(
        self, event_id: int, *, rejected: bool
    ) -> tuple[str, bool] | None:
        """Shared body for reject/unreject (§5.11): the model's original judgement stays
        on the row untouched — only `rejected_at` moves. Idempotent either direction."""
        with self.engine.begin() as connection:
            event = connection.execute(
                text(
                    """SELECT subject_key, rejected_at
                       FROM learning_event
                       WHERE id = :event_id AND subject_kind = 'grammar_point'
                         AND schema_version = :schema_version
                       FOR UPDATE"""
                ),
                {"event_id": event_id, "schema_version": LEARNING_EVENT_SCHEMA_VERSION},
            ).mappings().one_or_none()
            if event is None:
                return None
            already_rejected = event["rejected_at"] is not None
            if already_rejected == rejected:
                return str(event["subject_key"]), False
            connection.execute(
                text(
                    """UPDATE learning_event
                       SET rejected_at = CASE WHEN :rejected THEN now() ELSE NULL END
                       WHERE id = :event_id"""
                ),
                {"event_id": event_id, "rejected": rejected},
            )
        return str(event["subject_key"]), True

    def reject_learning_event(self, event_id: int) -> dict[str, Any] | None:
        """The learner says a piece of evidence was mistagged. The row and its payload
        are untouched — the model's judgement was a historical fact; this is a new one.
        Recomputes the projection the same way deleting source evidence would."""
        result = self._set_learning_event_rejected(event_id, rejected=True)
        if result is None:
            return None
        key, changed = result
        return self.reconcile_grammar_projection(key) if changed else self.get_grammar_point(key)

    def unreject_learning_event(self, event_id: int) -> dict[str, Any] | None:
        """Undoes an accidental reject."""
        result = self._set_learning_event_rejected(event_id, rejected=False)
        if result is None:
            return None
        key, changed = result
        return self.reconcile_grammar_projection(key) if changed else self.get_grammar_point(key)

    def invalidate_grammar_explanation(self, key: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """DELETE FROM grammar_explanation x USING grammar_point p
                       WHERE x.point_id = p.id AND p.key = :key"""
                ),
                {"key": key},
            )

    def save_grammar_explanation(
        self,
        key: str,
        content: str,
        *,
        prompt_version: str,
        evidence_fingerprint: str,
        evidence_refs: list[dict[str, Any]],
    ) -> None:
        with self.engine.begin() as connection:
            point_id = connection.execute(
                text("SELECT id FROM grammar_point WHERE key = :key"), {"key": key}
            ).scalar_one_or_none()
            if point_id is None:
                return
            connection.execute(
                text(
                    """INSERT INTO grammar_explanation
                       (point_id, content, prompt_version, evidence_fingerprint, evidence_refs)
                       VALUES (:point_id, :content, :prompt_version, :evidence_fingerprint,
                               CAST(:evidence_refs AS JSONB))
                       ON CONFLICT (point_id) DO UPDATE SET
                         content = EXCLUDED.content,
                         prompt_version = EXCLUDED.prompt_version,
                         evidence_fingerprint = EXCLUDED.evidence_fingerprint,
                         evidence_refs = EXCLUDED.evidence_refs"""
                ),
                {
                    "point_id": point_id,
                    "content": content,
                    "prompt_version": prompt_version,
                    "evidence_fingerprint": evidence_fingerprint,
                    "evidence_refs": json.dumps(evidence_refs, ensure_ascii=False),
                },
            )

    def corrections_touching(self, key: str, limit: int = 3) -> list[dict[str, Any]]:
        """Recent real mistakes for personalised explanation and cache provenance.

        `id` is the learning_event id (the reject endpoint's target), not the
        underlying chat_correction_item id.
        """
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT id, payload->>'original' AS original_fragment,
                              payload->>'replacement' AS replacement,
                              payload->>'reason_zh' AS reason_zh,
                              occurred_at AS created_at
                       FROM learning_event
                       WHERE subject_kind = 'grammar_point' AND subject_key = :key
                         AND schema_version = :schema_version
                         AND kind = 'correction_item' AND rejected_at IS NULL
                       ORDER BY occurred_at DESC, id DESC LIMIT :limit"""
                ),
                {
                    "key": key,
                    "limit": limit,
                    "schema_version": LEARNING_EVENT_SCHEMA_VERSION,
                },
            ).mappings().all()
        return [dict(row) for row in rows]

    def companion_questions_touching(self, key: str, limit: int = 3) -> list[dict[str, Any]]:
        """Recent explicit companion questions, which are encounters but not mistakes.

        `id` is the learning_event id, matching corrections_touching above.
        """
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT le.id, le.payload->>'question' AS question, le.occurred_at AS created_at,
                              s.text_ja AS context_ja
                       FROM learning_event le
                       LEFT JOIN segment s ON s.id = (le.payload->>'segment_id')::bigint
                       WHERE le.subject_kind = 'grammar_point' AND le.subject_key = :key
                         AND le.schema_version = :schema_version
                         AND le.kind = 'companion_question' AND le.rejected_at IS NULL
                       ORDER BY le.occurred_at DESC, le.id DESC LIMIT :limit"""
                ),
                {
                    "key": key,
                    "limit": limit,
                    "schema_version": LEARNING_EVENT_SCHEMA_VERSION,
                },
            ).mappings().all()
        return [dict(row) for row in rows]

    def grammar_evidence(self, key: str, limit_each: int = 3) -> list[dict[str, Any]]:
        evidence = [
            {"kind": "correction", **item} for item in self.corrections_touching(key, limit=limit_each)
        ]
        evidence.extend(
            {"kind": "companion_question", **item}
            for item in self.companion_questions_touching(key, limit=limit_each)
        )
        return sorted(evidence, key=lambda item: item["created_at"], reverse=True)

    def reconcile_grammar_projection(self, key: str) -> dict[str, Any] | None:
        """Rebuilds the projection after source evidence is deleted.

        Manual decisions and an explicit browse survive. Purely automatic rows with
        no remaining source evidence disappear, restoring the untouched state.
        """
        point = self.get_grammar_point(key)
        if point is None:
            return None
        has_evidence = bool(point["mistake_count"] or point["companion_question_count"])
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM grammar_explanation WHERE point_id = :point_id"),
                {"point_id": point["id"]},
            )
            if not has_evidence:
                if (
                    point.get("status_source") == "automatic"
                    and point.get("browsed_at") is None
                    and point.get("first_source") in {"correction", "companion"}
                ):
                    connection.execute(
                        text("DELETE FROM grammar_encounter WHERE point_id = :point_id"),
                        {"point_id": point["id"]},
                    )
                else:
                    connection.execute(
                        text(
                            """UPDATE grammar_encounter SET note = NULL,
                               last_source = CASE
                                   WHEN browsed_at IS NOT NULL THEN 'browse'
                                   WHEN last_source IN ('correction', 'companion') THEN first_source
                                   ELSE last_source
                               END
                               WHERE point_id = :point_id"""
                        ),
                        {"point_id": point["id"]},
                    )
            else:
                latest_source = point["latest_learning_evidence_source"]
                latest_at = point["latest_learning_evidence_at"]
                connection.execute(
                    text(
                        """INSERT INTO grammar_encounter
                           (point_id, status, status_source, first_source, last_source, note,
                            last_evidence_at)
                           VALUES (:point_id, 'encountered', 'automatic', :last_source, :last_source,
                                   :note, :last_evidence_at)
                           ON CONFLICT (point_id) DO UPDATE SET
                             last_source = EXCLUDED.last_source,
                             note = EXCLUDED.note,
                             last_evidence_at = EXCLUDED.last_evidence_at"""
                    ),
                    {
                        "point_id": point["id"],
                        "last_source": latest_source,
                        "note": point.get("latest_mistake"),
                        "last_evidence_at": latest_at,
                    },
                )
        return self.get_grammar_point(key)

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
        # §5.11: only a genuine new row is a new learning action. The merge-save
        # branch above returns before reaching here, so re-saving an existing word
        # never fires a second event. Best-effort like every other adapter: a failed
        # index must not turn a successful save into a failed one.
        self._record_event_with_trace(
            call_source="vocabulary_saved_index",
            subject_kind="vocabulary_word",
            subject_key=str(row["id"]),
            source_id=int(row["id"]),
            event={
                "kind": "vocabulary_saved",
                "source_table": "vocabulary",
                "source_id": int(row["id"]),
                "subject_kind": "vocabulary_word",
                "subject_key": str(row["id"]),
                "occurred_at": row["created_at"],
                "payload": {"word": row["word"], "reading": row["reading"], "meaning": row["meaning"]},
            },
        )
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
            box_before = int(current["box"])
            new_box = min(box_before + 1, 6) if correct else 1
            next_review_at = datetime.now(UTC) + self._REVIEW_INTERVALS[new_box]
            # §5.11: vocabulary.box/review_count/next_review_at stay the scheduling
            # projection the review flow reads; this insert is the immutable fact log
            # that projection alone cannot answer "which attempt, when, correct or not"
            # from, since a counter cannot be unwound into individual past events.
            attempt = connection.execute(
                text(
                    """INSERT INTO vocabulary_review_attempt
                       (vocabulary_id, correct, box_before, box_after)
                       VALUES (:vocabulary_id, :correct, :box_before, :box_after)
                       RETURNING id, created_at"""
                ),
                {
                    "vocabulary_id": vocabulary_id,
                    "correct": correct,
                    "box_before": box_before,
                    "box_after": new_box,
                },
            ).mappings().one()
            row = connection.execute(
                text(
                    """UPDATE vocabulary
                       SET box = :box, review_count = review_count + 1, next_review_at = :next_review_at
                       WHERE id = :id
                       RETURNING *"""
                ),
                {"box": new_box, "next_review_at": next_review_at, "id": vocabulary_id},
            ).mappings().one()
        self._record_event_with_trace(
            call_source="vocabulary_reviewed_index",
            subject_kind="vocabulary_word",
            subject_key=str(vocabulary_id),
            source_id=int(attempt["id"]),
            event={
                "kind": "vocabulary_reviewed",
                "source_table": "vocabulary_review_attempt",
                "source_id": int(attempt["id"]),
                "subject_kind": "vocabulary_word",
                "subject_key": str(vocabulary_id),
                "occurred_at": attempt["created_at"],
                "payload": {"correct": correct, "box_before": box_before, "box_after": new_box},
            },
        )
        return self._vocabulary_row(row)

    # ------------------------------------------------------------------
    # Collections and deletion (§15). Database-only: the OSS and local-file side of a
    # delete is orchestrated by the caller, because the order matters (§15.7) and the
    # repository has no business holding a bucket client.
    # ------------------------------------------------------------------

    def material_media_paths(self, material_id: int) -> list[str]:
        """Local files registered for a material, read *before* the row is deleted.

        After the cascade runs these paths are unrecoverable, which is why §15.7 fixes the
        order: read here, delete the bytes, delete the row.
        """

        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT local_path FROM media_asset
                       WHERE material_id = :material_id AND local_path IS NOT NULL"""
                ),
                {"material_id": material_id},
            ).mappings().all()
        return [str(row["local_path"]) for row in rows]

    def delete_material(self, material_id: int) -> bool:
        """Deletes the row and lets the database converge everything hanging off it.

        `segment`, `companion_message`, `job`, `media_asset` and `material_playback_state`
        are all `ON DELETE CASCADE`, and §4.3's triggers make the matching `learning_event`
        rows disappear with their sources — so this one statement is the whole database
        side. It does not touch OSS or the filesystem; see §15.7 for why the caller does
        those first.
        """

        with self.engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM material WHERE id = :id"), {"id": material_id}
            )
        return result.rowcount > 0

    def create_collection_with_sections(
        self,
        *,
        title: str,
        source_ref: str | None,
        source_path: str,
        boundaries: list[tuple[int, int | None]],
    ) -> tuple[int, list[int], int]:
        """Creates the collection, its sections and the single split job, in one transaction.

        One job for the whole cut, not one per section: the source is opened and decoded
        once, and a half-created collection must not be possible if the process dies
        between two inserts.
        """

        with self.engine.begin() as connection:
            collection_id = connection.execute(
                text("INSERT INTO material_collection (title) VALUES (:title) RETURNING id"),
                {"title": title},
            ).scalar_one()
            material_ids: list[int] = []
            for index, (start_ms, _) in enumerate(boundaries):
                material_id = connection.execute(
                    text(
                        """INSERT INTO material
                           (kind, title, source_type, source_ref, status,
                            collection_id, collection_index, source_offset_ms)
                           VALUES ('video', :title, 'file', :source_ref, 'pending',
                                   :collection_id, :index, :offset)
                           RETURNING id"""
                    ),
                    {
                        "title": f"{title} 第 {index + 1} 节",
                        "source_ref": source_ref,
                        "collection_id": collection_id,
                        "index": index,
                        "offset": start_ms,
                    },
                ).scalar_one()
                material_ids.append(int(material_id))
            sections = [
                {
                    "material_id": material_ids[index],
                    "index": index + 1,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                }
                for index, (start_ms, end_ms) in enumerate(boundaries)
            ]
            job_id = connection.execute(
                text(
                    """INSERT INTO job (kind, material_id, status, payload)
                       VALUES ('split_video', NULL, 'pending', CAST(:payload AS JSONB))
                       RETURNING id"""
                ),
                {
                    "payload": json.dumps(
                        {
                            "source_path": source_path,
                            "collection_id": int(collection_id),
                            "sections": sections,
                        },
                        ensure_ascii=False,
                    )
                },
            ).scalar_one()
        return int(collection_id), material_ids, int(job_id)

    def create_collection(self, title: str) -> dict[str, Any]:
        with self.engine.begin() as connection:
            row = connection.execute(
                text("INSERT INTO material_collection (title) VALUES (:title) RETURNING *"),
                {"title": title},
            ).mappings().one()
        return dict(row)

    #: One definition of a collection row. The detail endpoint and the list must return the
    #: same shape — they did not at first, and the detail screen would have failed to decode
    #: on the very first open (§15.5).
    _COLLECTION_SELECT = """SELECT c.*,
                  count(m.id) AS section_count,
                  count(m.id) FILTER (WHERE m.status = 'ready') AS ready_count,
                  coalesce(sum(m.duration_ms), 0) AS total_duration_ms
           FROM material_collection c
           LEFT JOIN material m ON m.collection_id = c.id"""

    def collections(self) -> list[dict[str, Any]]:
        """Newest first, with the counts derived on read.

        §15.5 keeps no aggregate state on the collection itself: a stored "3 of 12
        transcribed" is a second version of a fact that can disagree with the sections.
        """

        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""{self._COLLECTION_SELECT}
                        GROUP BY c.id
                        ORDER BY c.created_at DESC, c.id DESC"""
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    def collection_sections(self, collection_id: int) -> list[dict[str, Any]]:
        """Thin wrapper over `list_materials` so a section carries exactly the same fields
        as a material in the library — including the delivery keys the player needs."""

        return self.list_materials(collection_id=collection_id)

    def get_collection(self, collection_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(f"{self._COLLECTION_SELECT} WHERE c.id = :id GROUP BY c.id"),
                {"id": collection_id},
            ).mappings().first()
        return dict(row) if row else None

    def delete_collection(self, collection_id: int) -> bool:
        """Sections cascade from the collection, and everything else cascades from them."""

        with self.engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM material_collection WHERE id = :id"), {"id": collection_id}
            )
        return result.rowcount > 0

    def resume_hint(self) -> dict[str, Any] | None:
        """§5.18: one fact about where you left off, or nothing at all.

        Returns structured fields, not a sentence — the wording is UI copy and belongs
        to §1.5. What lives here is the *selection rule*, so that "which single thing is
        worth saying" is defined in exactly one place.

        Nothing is invented: both branches read tables that already exist. When neither
        matches, the answer is None and the row simply does not appear (§1.4 — an empty
        shelf is allowed to read as empty, not as an invitation).
        """

        with self.engine.connect() as connection:
            interrupted = connection.execute(
                text(
                    """SELECT m.id, m.kind, m.title, p.position_ms, p.updated_at
                       FROM material_playback_state p
                       JOIN material m ON m.id = p.material_id
                       WHERE m.status = 'ready'
                         AND m.duration_ms IS NOT NULL
                         AND m.duration_ms > 0
                         AND p.position_ms::numeric / m.duration_ms > :low
                         AND p.position_ms::numeric / m.duration_ms < :high
                       ORDER BY p.updated_at DESC, p.material_id DESC
                       LIMIT 1"""
                ),
                {"low": RESUME_MIN_RATIO, "high": RESUME_MAX_RATIO},
            ).mappings().first()
            if interrupted is not None:
                sentence_number: int | None = None
                if interrupted["kind"] == "reading":
                    # Reading says "sentence N"; a timestamp is the natural unit for video
                    # but a strange one for an article (§5.18).
                    latest_idx = connection.execute(
                        text(
                            """SELECT max(idx) FROM segment
                               WHERE material_id = :material_id AND start_ms <= :position_ms"""
                        ),
                        {
                            "material_id": int(interrupted["id"]),
                            "position_ms": int(interrupted["position_ms"]),
                        },
                    ).scalar()
                    if latest_idx is not None:
                        sentence_number = int(latest_idx) + 1
                return {
                    "kind": "material",
                    "material_id": int(interrupted["id"]),
                    "material_kind": interrupted["kind"],
                    "title": interrupted["title"],
                    "position_ms": int(interrupted["position_ms"]),
                    "sentence_number": sentence_number,
                    "at": interrupted["updated_at"],
                }

            # Only points the learner has run into but has not called understood. An
            # understood point resurfacing is not something to be nudged about, and
            # §5.10 forbids automation quietly downgrading that state.
            encountered = connection.execute(
                text(
                    """SELECT p.key, p.title_ja, p.title_zh, e.last_evidence_at
                       FROM grammar_encounter e
                       JOIN grammar_point p ON p.id = e.point_id
                       WHERE e.status = 'encountered'
                       ORDER BY e.last_evidence_at DESC, p.id DESC
                       LIMIT 1"""
                )
            ).mappings().first()
            if encountered is not None:
                return {
                    "kind": "grammar",
                    "grammar_key": encountered["key"],
                    "title_ja": encountered["title_ja"],
                    "title_zh": encountered["title_zh"],
                    "at": encountered["last_evidence_at"],
                }
        return None

    # ------------------------------------------------------------------
    # Private journal (§14) — nothing below this line touches learning data.
    #
    # Kept physically at the end of the class and behind this banner because the
    # isolation is the feature (§14.3). None of these methods may grow a
    # learning_event write, a decision_trace row, grammar evidence, or a read of
    # any learning table; nothing on the learning side may read journal rows.
    # If a future change needs to cross that line, it changes §14 first.
    # ------------------------------------------------------------------

    def add_journal_entry(self, body: str) -> dict[str, Any]:
        with self.engine.begin() as connection:
            row = connection.execute(
                text("INSERT INTO journal_entry (body) VALUES (:body) RETURNING *"),
                {"body": body},
            ).mappings().one()
        return dict(row)

    def update_journal_entry(self, entry_id: int, body: str) -> dict[str, Any] | None:
        """Only for fixing a typo in something already said; replies are left alone."""

        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    "UPDATE journal_entry SET body = :body WHERE id = :id RETURNING *"
                ),
                {"body": body, "id": entry_id},
            ).mappings().first()
        return dict(row) if row else None

    def delete_journal_entry(self, entry_id: int) -> bool:
        """Hard delete (§13.7): the foreign key cascades the replies with it.

        Not a list-level hide — after this the row is gone from the database, which is
        the whole reason this table exists here rather than in a commercial app.
        """

        with self.engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM journal_entry WHERE id = :id"), {"id": entry_id}
            )
        return result.rowcount > 0

    def add_journal_reply(
        self,
        entry_id: int,
        body: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    """INSERT INTO journal_reply
                       (entry_id, body, model_provider, model_name, prompt_version)
                       VALUES (:entry_id, :body, :provider, :model, :prompt_version)
                       RETURNING *"""
                ),
                {
                    "entry_id": entry_id,
                    "body": body,
                    "provider": provider,
                    "model": model,
                    "prompt_version": prompt_version,
                },
            ).mappings().one()
        return dict(row)

    def journal_timeline(self, limit: int = JOURNAL_TIMELINE_LIMIT) -> list[dict[str, Any]]:
        """Most recent entries with their replies, oldest first for display.

        Bounded on purpose. §5.17 set the rule that one interaction must not get more
        expensive as history grows, and this is both the display query and the source
        of the model's context (§14.2 keeps the last 20).
        """

        with self.engine.connect() as connection:
            entries = connection.execute(
                text(
                    """SELECT * FROM (
                           SELECT * FROM journal_entry ORDER BY id DESC LIMIT :limit
                       ) recent ORDER BY id"""
                ),
                {"limit": limit},
            ).mappings().all()
            if not entries:
                return []
            replies = connection.execute(
                text(
                    """SELECT * FROM journal_reply
                       WHERE entry_id = ANY(:ids)
                       ORDER BY entry_id, created_at, id"""
                ),
                {"ids": [int(entry["id"]) for entry in entries]},
            ).mappings().all()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for reply in replies:
            grouped.setdefault(int(reply["entry_id"]), []).append(dict(reply))
        return [{**dict(entry), "replies": grouped.get(int(entry["id"]), [])} for entry in entries]
