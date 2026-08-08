import os
import uuid
from typing import Any

import pytest
from app import main
from app.config import Settings
from app.db import apply_schema, make_engine
from app.grammar_catalogue import GRAMMAR_CATALOGUE
from app.repository import Repository
from sqlalchemy import create_engine, text


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
            [
                {
                    "segment_idx": 0,
                    "idx": 0,
                    "surface": "雨",
                    "reading": "あめ",
                    "start_ms": 0,
                    "end_ms": 500,
                }
            ],
        )
        assert repository.get_tokens(material_id)[0]["surface"] == "雨"
        assert repository.get_tokens(material_id)[0]["reading"] == "あめ"
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


@pytest.mark.integration
def test_chat_schema_migrates_legacy_personal_messages() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    schema_name = f"harvest_chat_migration_{uuid.uuid4().hex}"
    admin_engine = create_engine(database_url, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
    migration_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema_name}"},
    )
    try:
        with migration_engine.begin() as connection:
            connection.exec_driver_sql(
                """CREATE TABLE chat_message (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )"""
            )
            connection.execute(
                text("INSERT INTO chat_message (session_id, role, content) VALUES ('personal', 'user', '以前の会話')")
            )

        apply_schema(migration_engine)

        with migration_engine.connect() as connection:
            session = connection.execute(
                text("SELECT id, topic FROM chat_session WHERE id = 'personal'")
            ).mappings().one()
            message = connection.execute(
                text("SELECT session_id, content FROM chat_message WHERE session_id = 'personal'")
            ).mappings().one()
            foreign_key_count = connection.execute(
                text(
                    """SELECT count(*) FROM pg_constraint
                    WHERE conname = 'fk_chat_message_session'
                      AND conrelid = 'chat_message'::regclass"""
                )
            ).scalar_one()
        assert dict(session) == {"id": "personal", "topic": "旧版聊天"}
        assert dict(message) == {"session_id": "personal", "content": "以前の会話"}
        assert foreign_key_count == 1
    finally:
        migration_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        admin_engine.dispose()


@pytest.mark.integration
def test_chat_repository_session_correction_filters_and_deletes() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    session_id = f"test-{uuid.uuid4()}"
    other_session_id = f"test-{uuid.uuid4()}"
    try:
        session, opener = repository.create_chat_session(
            session_id=session_id,
            topic="週末",
            starter_id="daily-weekend",
            assistant_content="週末について話しましょう。何をしたいですか？",
        )
        repository.create_chat_session(
            session_id=other_session_id,
            topic="音楽",
            starter_id=None,
            assistant_content="音楽について話しましょう。",
        )
        user, correction, assistant = repository.complete_chat_turn(
            session_id=session_id,
            user_content="昨日映画を見る。",
            assistant_content="面白そうですね。どんな映画でしたか？",
            correction={
                "corrected_text": "昨日、映画を見ました。",
                "summary_zh": "已经发生的事情使用过去时。",
                "items": [
                    {
                        "original": "見る",
                        "replacement": "見ました",
                        "reason_zh": "使用过去时并保持礼貌体。",
                        "category": "grammar",
                    }
                ],
            },
        )
        repository.complete_chat_turn(
            session_id=other_session_id,
            user_content="音楽が好きです。",
            assistant_content="私も好きです。何をよく聴きますか？",
            correction=None,
        )

        assert session["starter_id"] == "daily-weekend"
        assert opener["role"] == "assistant"
        assert user["role"] == "user"
        assert assistant["role"] == "assistant"
        assert correction is not None
        assert correction["items"][0]["category"] == "grammar"
        assert [message["content"] for message in repository.chat_messages(other_session_id)] == [
            "音楽について話しましょう。",
            "音楽が好きです。",
            "私も好きです。何をよく聴きますか？",
        ]

        detail = repository.chat_session_detail(session_id)
        assert detail is not None
        assert detail["session"]["topic"] == "週末"
        assert len(detail["messages"]) == 3
        assert len(detail["corrections"]) == 1
        correction_id = int(detail["corrections"][0]["id"])
        assert repository.chat_corrections(query="过去时")[0]["id"] == correction_id
        assert repository.chat_corrections(topic="週末")[0]["id"] == correction_id
        assert repository.chat_corrections(category="grammar")[0]["id"] == correction_id
        assert repository.chat_corrections(category="register") == []
        assert repository.chat_corrections(cursor=correction_id, session_id=session_id) == []
        assert "grammar" in repository.recent_correction_guidance()

        assert repository.delete_chat_correction(correction_id) is True
        assert repository.chat_corrections(session_id=session_id) == []
        assert len(repository.chat_messages(session_id)) == 3

        _, second_correction, _ = repository.complete_chat_turn(
            session_id=session_id,
            user_content="映画は楽しいだ。",
            assistant_content="そうですね。最近は何を見ましたか？",
            correction={
                "corrected_text": "映画は楽しいです。",
                "summary_zh": "形容词礼貌体不接「だ」。",
                "items": [
                    {
                        "original": "楽しいだ",
                        "replacement": "楽しいです",
                        "reason_zh": "い形容词直接接「です」。",
                        "category": "grammar",
                    }
                ],
            },
        )
        assert second_correction is not None
        assert repository.delete_chat_session(session_id) is True
        with engine.connect() as connection:
            counts = connection.execute(
                text(
                    """SELECT
                        (SELECT count(*) FROM chat_message WHERE session_id = :session_id) AS messages,
                        (SELECT count(*) FROM chat_correction WHERE session_id = :session_id) AS corrections,
                        (SELECT count(*) FROM chat_correction_item ci
                            JOIN chat_correction c ON c.id = ci.correction_id
                            WHERE c.session_id = :session_id) AS items"""
                ),
                {"session_id": session_id},
            ).mappings().one()
        assert dict(counts) == {"messages": 0, "corrections": 0, "items": 0}
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session_id})
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": other_session_id})
        engine.dispose()


@pytest.mark.integration
def test_chat_turn_transaction_rolls_back_every_partial_row() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    session_id = f"test-{uuid.uuid4()}"
    legacy_session_id = f"legacy-{uuid.uuid4()}"
    try:
        repository.create_chat_session(
            session_id=session_id,
            topic="原子性",
            starter_id=None,
            assistant_content="始めましょう。",
        )
        with pytest.raises(Exception):
            repository.complete_chat_turn(
                session_id=session_id,
                user_content="partial user",
                assistant_content="partial assistant",
                correction={
                    "corrected_text": "corrected",
                    "summary_zh": "summary",
                    "items": [{"original": "old", "replacement": "new", "reason_zh": "reason"}],
                },
            )
        assert [message["content"] for message in repository.chat_messages(session_id)] == ["始めましょう。"]
        assert repository.chat_corrections(session_id=session_id) == []

        with pytest.raises(Exception):
            repository.complete_chat_turn(
                session_id=legacy_session_id,
                user_content="partial legacy user",
                assistant_content="partial legacy assistant",
                correction={
                    "corrected_text": "corrected",
                    "summary_zh": "summary",
                    "items": [{"original": "old", "replacement": "new", "reason_zh": "reason"}],
                },
                create_session_topic="旧版聊天",
            )
        assert repository.get_chat_session(legacy_session_id) is None
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session_id})
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": legacy_session_id})
        engine.dispose()


@pytest.mark.integration
@pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient` is deprecated")
def test_chat_api_end_to_end_with_mock_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    unique_topic = f"週末-{uuid.uuid4()}"
    responses = [
        """{
          "correction":{"needed":false,"corrected_text":null,"summary_zh":null,"items":[]},
          "reply_ja":"週末について話しましょう。",
          "follow_up_ja":"今週末は何をしたいですか？"
        }""",
        """{
          "correction":{
            "needed":true,
            "corrected_text":"昨日、映画を見ました。",
            "summary_zh":"已经发生的事情使用过去时。",
            "items":[{
              "original":"見る","replacement":"見ました","reason_zh":"使用过去时。","category":"grammar"
            }]
          },
          "reply_ja":"いいですね。映画館で見たんですか？",
          "follow_up_ja":"どんな映画でしたか？"
        }""",
    ]

    class MockLLM:
        def __init__(self, settings: Settings) -> None:
            pass

        def close(self) -> None:
            pass

        def reply(self, messages: list[dict[str, str]], **options: Any) -> str:
            return responses.pop(0)

    monkeypatch.setattr(main, "make_engine", lambda: engine)
    monkeypatch.setattr(main, "LLMService", MockLLM)
    session_id: str | None = None
    with TestClient(main.app) as client:
        topics = client.get("/chat/topics")
        assert topics.status_code == 200
        assert len(topics.json()) == 16

        created = client.post("/chat/sessions", json={"topic": unique_topic})
        assert created.status_code == 201
        assert created.json()["session"]["topic"] == unique_topic
        assert created.json()["assistant"]["content"].endswith("今週末は何をしたいですか？")
        session_id = created.json()["session"]["id"]

        turn = client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "昨日映画を見る。"},
        )
        assert turn.status_code == 200
        assert turn.json()["correction"]["items"][0]["category"] == "grammar"
        correction_id = int(turn.json()["correction"]["id"])

        detail = client.get(f"/chat/sessions/{session_id}")
        assert detail.status_code == 200
        assert [message["role"] for message in detail.json()["messages"]] == [
            "assistant",
            "user",
            "assistant",
        ]
        corrections = client.get(
            "/chat/corrections",
            params={"query": "过去时", "topic": unique_topic, "category": "grammar"},
        )
        assert corrections.status_code == 200
        assert [item["id"] for item in corrections.json()] == [correction_id]

        assert client.delete(f"/chat/corrections/{correction_id}").status_code == 204
        assert len(client.get(f"/chat/sessions/{session_id}").json()["messages"]) == 3
        assert client.delete(f"/chat/sessions/{session_id}").status_code == 204
        assert client.get(f"/chat/sessions/{session_id}").status_code == 404

    assert responses == []
    engine.dispose()


@pytest.mark.integration
def test_list_jobs_joins_material_title_and_filters() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    material_id, first_job_id = repository.create_material_with_job(
        title="排序测试材料",
        source_type="paste",
        source_ref=None,
        job_kind="tts",
        payload={"text": "雨です。"},
    )
    material_id_2, _ = repository.create_material_with_job(
        title="第二份材料",
        source_type="url",
        source_ref="https://example.com",
        job_kind="fetch",
        payload={},
    )
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE material SET status = 'ready' WHERE id = :id"), {"id": material_id})
        second_job_id = repository.enqueue_job(kind="asr", material_id=material_id, payload={})
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE job SET status = 'done' WHERE id = :job_id"), {"job_id": second_job_id}
            )

        jobs = repository.list_jobs()
        assert [job["id"] for job in jobs][:1] == [second_job_id]
        assert all("material_title" in job for job in jobs)

        by_kind = repository.list_jobs(kind="tts")
        assert [job["id"] for job in by_kind] == [first_job_id]
        assert repository.count_jobs(kind="tts") == 1

        done = repository.list_jobs(status="done")
        assert [job["id"] for job in done] == [second_job_id]
        assert repository.count_jobs(status="done") == 1

        # list_jobs resolves material titles and status filter works
        titled = repository.list_jobs(status="done", kind="asr")
        assert titled and titled[0]["material_title"] == "排序测试材料"
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM material WHERE id IN (:a, :b)"), {"a": material_id, "b": material_id_2})
        engine.dispose()


@pytest.mark.integration
def test_list_materials_status_filter_and_pagination_keep_no_arg_contract() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    ids: list[int] = []
    for index in range(3):
        material_id, _ = repository.create_material_with_job(
            title=f"分页材料{index}",
            source_type="paste",
            source_ref=None,
            job_kind="tts",
            payload={"text": "雨です。"},
        )
        ids.append(material_id)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE material SET status = 'ready' WHERE id = :id"), {"id": ids[0]}
            )
            connection.execute(
                text("UPDATE material SET status = 'failed' WHERE id = :id"), {"id": ids[1]}
            )

        ready = repository.list_materials(status="ready")
        assert [material["id"] for material in ready] == [ids[0]]
        assert repository.count_materials(status="ready") == 1

        page = repository.list_materials(limit=2, offset=0)
        assert len(page) == 2
        assert repository.count_materials() == 3

        # No-arg behaviour unchanged: everything, newest first (iOS /materials contract)
        assert len(repository.list_materials()) == 3
        assert repository.list_materials()[0]["id"] == ids[2]
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM material WHERE id = ANY(:ids)"), {"ids": ids})
        engine.dispose()


@pytest.mark.integration
def test_video_playback_state_upserts_and_cascades_with_material() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    material_id, _ = repository.create_material_with_job(
        title="续播测试视频",
        source_type="file",
        source_ref="resume.mp4",
        job_kind="transcode",
        payload={},
        kind="video",
    )
    try:
        initial = repository.get_playback_state(material_id)
        assert initial is not None
        assert initial["position_ms"] == 0
        assert initial["updated_at"] is None

        assert repository.save_playback_state(material_id, 12_345)["position_ms"] == 12_345
        assert repository.save_playback_state(material_id, 67_890)["position_ms"] == 67_890
        assert repository.get_playback_state(material_id)["position_ms"] == 67_890

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM material WHERE id = :id"), {"id": material_id})
            remaining = connection.execute(
                text("SELECT count(*) FROM material_playback_state WHERE material_id = :id"),
                {"id": material_id},
            ).scalar_one()
        assert remaining == 0
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM material WHERE id = :id"), {"id": material_id})
        engine.dispose()


@pytest.mark.integration
def test_grammar_projection_preserves_learner_decisions_and_tracks_real_evidence() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    grammar_key = f"test-m0-{uuid.uuid4().hex}"
    session_id = f"test-{uuid.uuid4()}"
    material_id: int | None = None
    correction_ids: list[int] = []
    with engine.begin() as connection:
        point_id = connection.execute(
            text(
                """INSERT INTO grammar_point
                   (key, title_ja, title_zh, level, category, sort_order)
                   VALUES (:key, '～ておく', '预先做好', 'N4', '动词变形', 999999)
                   RETURNING id"""
            ),
            {"key": grammar_key},
        ).scalar_one()

    try:
        browsed = repository.mark_grammar_encounter(
            grammar_key,
            status="encountered",
            source="browse",
        )
        assert browsed is not None
        assert browsed["first_source"] == "browse"
        assert browsed["last_source"] == "browse"
        assert browsed["has_mistake"] is False

        repository.save_grammar_explanation(
            grammar_key,
            "浏览后生成的讲解",
            prompt_version="grammar-explanation-v2",
            evidence_fingerprint="empty-evidence",
            evidence_refs=[],
        )
        assert repository.get_grammar_point(grammar_key)["explanation"] == "浏览后生成的讲解"

        repository.create_chat_session(
            session_id=session_id,
            topic="M0 语法证据",
            starter_id=None,
            assistant_content="始めましょう。",
        )
        _, first_correction, _ = repository.complete_chat_turn(
            session_id=session_id,
            user_content="旅行の前に切符を買うておきます。",
            assistant_content="準備が早いですね。",
            correction={
                "corrected_text": "旅行の前に切符を買っておきます。",
                "summary_zh": "使用正确的て形连接～ておく。",
                "items": [
                    {
                        "original": "買うておきます",
                        "replacement": "買っておきます",
                        "reason_zh": "五段动词「買う」的て形是「買って」。",
                        "category": "grammar",
                        "grammar_key": grammar_key,
                    }
                ],
            },
        )
        assert first_correction is not None
        correction_ids.append(int(first_correction["id"]))

        after_first_mistake = repository.get_grammar_point(grammar_key)
        assert after_first_mistake is not None
        assert after_first_mistake["first_source"] == "browse"
        assert after_first_mistake["last_source"] == "correction"
        assert after_first_mistake["has_mistake"] is True
        assert after_first_mistake["mistake_count"] == 1
        assert after_first_mistake["latest_mistake"] == "買うておきます"
        assert after_first_mistake["explanation"] is None

        understood = repository.mark_grammar_encounter(
            grammar_key,
            status="understood",
            source="manual",
            manual=True,
        )
        assert understood is not None
        assert understood["status"] == "understood"
        assert understood["status_source"] == "manual"
        assert understood["needs_attention"] is False

        _, second_correction, _ = repository.complete_chat_turn(
            session_id=session_id,
            user_content="明日の会議を調べるておきます。",
            assistant_content="それなら安心ですね。",
            correction={
                "corrected_text": "明日の会議を調べておきます。",
                "summary_zh": "辞书形不能直接接～ておく。",
                "items": [
                    {
                        "original": "調べるておきます",
                        "replacement": "調べておきます",
                        "reason_zh": "先变成て形再接「おく」。",
                        "category": "grammar",
                        "grammar_key": grammar_key,
                    }
                ],
            },
        )
        assert second_correction is not None
        correction_ids.append(int(second_correction["id"]))

        after_new_mistake = repository.get_grammar_point(grammar_key)
        assert after_new_mistake is not None
        assert after_new_mistake["status"] == "understood"
        assert after_new_mistake["status_source"] == "manual"
        assert after_new_mistake["needs_attention"] is True
        assert after_new_mistake["latest_mistake"] == "調べるておきます"

        needs_review = repository.mark_grammar_encounter(
            grammar_key,
            status="encountered",
            source="manual",
            manual=True,
        )
        assert needs_review is not None
        assert needs_review["status"] == "encountered"
        assert needs_review["status_source"] == "manual"
        assert needs_review["first_source"] == "browse"

        repository.save_grammar_explanation(
            grammar_key,
            "纠错后的讲解",
            prompt_version="grammar-explanation-v2",
            evidence_fingerprint="correction-evidence",
            evidence_refs=[{"kind": "correction", "id": correction_ids[-1]}],
        )
        material_id, _ = repository.create_material_with_job(
            title="M0 陪读证据",
            source_type="paste",
            source_ref=None,
            job_kind="tts",
            payload={"text": "旅行の前に予約しておきます。"},
        )
        question = repository.add_companion_message(
            material_id,
            None,
            "user",
            "这里为什么要用「ておく」？",
        )
        assert repository.record_companion_grammar_evidence(
            int(question["id"]), [grammar_key, "unknown-key", grammar_key]
        ) == [grammar_key]

        with engine.begin() as connection:
            connection.execute(
                text(
                    """DELETE FROM learning_event
                       WHERE source_table = 'companion_message' AND source_id = :source_id"""
                ),
                {"source_id": int(question["id"])},
            )
        assert repository.backfill_learning_events() == [grammar_key]
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    """SELECT backfilled FROM learning_event
                       WHERE source_table = 'companion_message' AND source_id = :source_id"""
                ),
                {"source_id": int(question["id"])},
            ).scalar_one() is True

        after_question = repository.get_grammar_point(grammar_key)
        assert after_question is not None
        assert after_question["has_companion_question"] is True
        assert after_question["companion_question_count"] == 1
        assert after_question["latest_question"] == "这里为什么要用「ておく」？"
        assert after_question["mistake_count"] == 2
        assert after_question["explanation"] is None

        evidence = repository.grammar_evidence(grammar_key)
        assert {item["kind"] for item in evidence} == {"correction", "companion_question"}
        evidence_refs = [{"kind": str(item["kind"]), "id": int(item["id"])} for item in evidence]
        repository.save_grammar_explanation(
            grammar_key,
            "带证据来源的讲解",
            prompt_version="grammar-explanation-v2",
            evidence_fingerprint="fingerprint-v2",
            evidence_refs=evidence_refs,
        )
        cached = repository.get_grammar_point(grammar_key)
        assert cached is not None
        assert cached["explanation_prompt_version"] == "grammar-explanation-v2"
        assert cached["explanation_evidence_fingerprint"] == "fingerprint-v2"
        assert cached["explanation_evidence_refs"] == evidence_refs

        for correction_id in correction_ids:
            assert repository.delete_chat_correction(correction_id) is True
        without_mistakes = repository.get_grammar_point(grammar_key)
        assert without_mistakes is not None
        assert without_mistakes["has_mistake"] is False
        assert without_mistakes["has_companion_question"] is True
        assert without_mistakes["status"] == "encountered"
        assert without_mistakes["status_source"] == "manual"
        assert without_mistakes["first_source"] == "browse"
        assert without_mistakes["explanation"] is None

        with engine.begin() as connection:
            # The source-row trigger must clean the polymorphic event reference even
            # when companion_message disappears through a material cascade.
            connection.execute(text("DELETE FROM material WHERE id = :id"), {"id": material_id})
        material_id = None
        reconciled = repository.reconcile_grammar_projection(grammar_key)
        assert reconciled is not None
        assert reconciled["has_companion_question"] is False
        assert reconciled["status"] == "encountered"
        assert reconciled["status_source"] == "manual"
        assert reconciled["first_source"] == "browse"
    finally:
        with engine.begin() as connection:
            if material_id is not None:
                connection.execute(text("DELETE FROM material WHERE id = :id"), {"id": material_id})
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session_id})
            connection.execute(text("DELETE FROM grammar_point WHERE id = :id"), {"id": point_id})
        engine.dispose()


@pytest.mark.integration
def test_deleting_the_only_automatic_grammar_evidence_restores_untouched_state() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    grammar_key = f"test-m0-{uuid.uuid4().hex}"
    session_id = f"test-{uuid.uuid4()}"
    with engine.begin() as connection:
        point_id = connection.execute(
            text(
                """INSERT INTO grammar_point
                   (key, title_ja, title_zh, level, category, sort_order)
                   VALUES (:key, '～た', '简体过去', 'N5', '动词变形', 999999)
                   RETURNING id"""
            ),
            {"key": grammar_key},
        ).scalar_one()

    try:
        repository.create_chat_session(
            session_id=session_id,
            topic="M0 自动投影",
            starter_id=None,
            assistant_content="始めましょう。",
        )
        _, correction, _ = repository.complete_chat_turn(
            session_id=session_id,
            user_content="昨日、映画を見る。",
            assistant_content="どんな映画でしたか？",
            correction={
                "corrected_text": "昨日、映画を見た。",
                "summary_zh": "过去发生的动作使用过去形。",
                "items": [
                    {
                        "original": "見る",
                        "replacement": "見た",
                        "reason_zh": "昨天发生的动作要使用过去形。",
                        "category": "grammar",
                        "grammar_key": grammar_key,
                    }
                ],
            },
        )
        assert correction is not None
        projected = repository.get_grammar_point(grammar_key)
        assert projected is not None
        assert projected["status"] == "encountered"
        assert projected["status_source"] == "automatic"
        assert projected["first_source"] == "correction"

        assert repository.delete_chat_session(session_id) is True
        untouched = repository.get_grammar_point(grammar_key)
        assert untouched is not None
        assert untouched["status"] is None
        assert untouched["status_source"] is None
        assert untouched["first_source"] is None
        assert untouched["has_mistake"] is False
        assert untouched["needs_attention"] is False
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session_id})
            connection.execute(text("DELETE FROM grammar_point WHERE id = :id"), {"id": point_id})
        engine.dispose()


@pytest.mark.integration
def test_deleting_a_mistake_does_not_forget_a_later_explicit_browse() -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    grammar_key = f"test-m0-{uuid.uuid4().hex}"
    session_id = f"test-{uuid.uuid4()}"
    with engine.begin() as connection:
        point_id = connection.execute(
            text(
                """INSERT INTO grammar_point
                   (key, title_ja, title_zh, level, category, sort_order)
                   VALUES (:key, '～た', '简体过去', 'N5', '动词变形', 999999)
                   RETURNING id"""
            ),
            {"key": grammar_key},
        ).scalar_one()

    try:
        repository.create_chat_session(
            session_id=session_id,
            topic="M0 浏览保留",
            starter_id=None,
            assistant_content="始めましょう。",
        )
        repository.complete_chat_turn(
            session_id=session_id,
            user_content="昨日、映画を見る。",
            assistant_content="どんな映画でしたか？",
            correction={
                "corrected_text": "昨日、映画を見た。",
                "summary_zh": "过去发生的动作使用过去形。",
                "items": [
                    {
                        "original": "見る",
                        "replacement": "見た",
                        "reason_zh": "昨天发生的动作要使用过去形。",
                        "category": "grammar",
                        "grammar_key": grammar_key,
                    }
                ],
            },
        )
        browsed = repository.mark_grammar_encounter(
            grammar_key,
            status="encountered",
            source="browse",
        )
        assert browsed is not None
        assert browsed["first_source"] == "correction"
        assert browsed["last_source"] == "browse"
        assert browsed["browsed_at"] is not None

        assert repository.delete_chat_session(session_id) is True
        after_delete = repository.get_grammar_point(grammar_key)
        assert after_delete is not None
        assert after_delete["status"] == "encountered"
        assert after_delete["status_source"] == "automatic"
        assert after_delete["first_source"] == "correction"
        assert after_delete["last_source"] == "browse"
        assert after_delete["browsed_at"] is not None
        assert after_delete["has_mistake"] is False
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session_id})
            connection.execute(text("DELETE FROM grammar_point WHERE id = :id"), {"id": point_id})
        engine.dispose()


@pytest.mark.integration
def test_learning_event_dual_write_reject_unreject_and_cleanup_on_delete() -> None:
    """§5.11's precise contract: corrections and companion questions dual-write into
    learning_event with the source row's real occurred_at; the projection reads that
    table (excluding rejected_at); reject/unreject are idempotent and recompute the
    projection like deleting source evidence would; deleting the correction cleans up
    the orphaned learning_event row instead of leaving it counted forever."""
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    grammar_key = f"test-m1-{uuid.uuid4().hex}"
    session_id = f"test-{uuid.uuid4()}"
    with engine.begin() as connection:
        point_id = connection.execute(
            text(
                """INSERT INTO grammar_point
                   (key, title_ja, title_zh, level, category, sort_order)
                   VALUES (:key, '～ておく', '预先做好', 'N4', '动词变形', 999999)
                   RETURNING id"""
            ),
            {"key": grammar_key},
        ).scalar_one()

    try:
        repository.create_chat_session(
            session_id=session_id,
            topic="M1 学习事件",
            starter_id=None,
            assistant_content="始めましょう。",
        )
        _, correction, _ = repository.complete_chat_turn(
            session_id=session_id,
            user_content="旅行の前に切符を買うておきます。",
            assistant_content="準備が早いですね。",
            correction={
                "corrected_text": "旅行の前に切符を買っておきます。",
                "summary_zh": "使用正确的て形连接～ておく。",
                "items": [
                    {
                        "original": "買うておきます",
                        "replacement": "買っておきます",
                        "reason_zh": "五段动词「買う」的て形是「買って」。",
                        "category": "grammar",
                        "grammar_key": grammar_key,
                    }
                ],
            },
        )
        assert correction is not None
        correction_item_id = int(correction["items"][0]["id"])

        with engine.connect() as connection:
            event = connection.execute(
                text(
                    """SELECT id, kind, source_table, source_id, occurred_at, payload
                       FROM learning_event
                       WHERE source_table = 'chat_correction_item' AND source_id = :source_id"""
                ),
                {"source_id": correction_item_id},
            ).mappings().one()
            correction_created_at = connection.execute(
                text("SELECT created_at FROM chat_correction WHERE id = :id"),
                {"id": int(correction["id"])},
            ).scalar_one()
        assert event["kind"] == "correction_item"
        assert event["source_table"] == "chat_correction_item"
        # occurred_at is the correction's real time, not the learning_event write time.
        assert event["occurred_at"] == correction_created_at
        assert event["payload"]["original"] == "買うておきます"

        # Simulate an upgrade from M0: the legacy grammar_key exists but its event
        # envelope does not. Startup replay must restore it once and mark provenance.
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM learning_event WHERE id = :id"),
                {"id": int(event["id"])},
            )
        assert repository.backfill_learning_events() == [grammar_key]
        assert repository.backfill_learning_events() == []
        with engine.connect() as connection:
            event = connection.execute(
                text(
                    """SELECT id, backfilled, occurred_at, payload
                       FROM learning_event
                       WHERE source_table = 'chat_correction_item' AND source_id = :source_id"""
                ),
                {"source_id": correction_item_id},
            ).mappings().one()
        assert event["backfilled"] is True
        assert event["occurred_at"] == correction_created_at
        event_id = int(event["id"])

        # If event indexing committed but projection update failed, the next replay
        # repairs the missing projection without duplicating the event.
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM grammar_encounter WHERE point_id = :point_id"),
                {"point_id": point_id},
            )
        assert repository.backfill_learning_events() == [grammar_key]
        assert repository.backfill_learning_events() == []

        # A duplicate dual write (e.g. a retried request) must not double-count.
        with engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO learning_event
                       (kind, source_table, source_id, subject_kind, subject_key, confidence,
                        occurred_at, payload)
                       VALUES ('correction_item', 'chat_correction_item', :source_id, 'grammar_point',
                               :subject_key, 1.0, :occurred_at, CAST(:payload AS JSONB))
                       ON CONFLICT (source_table, source_id, subject_kind, subject_key) DO NOTHING"""
                ),
                {
                    "source_id": correction_item_id,
                    "subject_key": grammar_key,
                    "occurred_at": correction_created_at,
                    "payload": '{"original": "x"}',
                },
            )
            count = connection.execute(
                text("SELECT count(*) FROM learning_event WHERE source_table = 'chat_correction_item'"
                     " AND source_id = :source_id"),
                {"source_id": correction_item_id},
            ).scalar_one()
        assert count == 1

        before_reject = repository.get_grammar_point(grammar_key)
        assert before_reject is not None
        assert before_reject["mistake_count"] == 1
        assert before_reject["status"] == "encountered"

        rejected = repository.reject_learning_event(event_id)
        assert rejected is not None
        assert rejected["mistake_count"] == 0
        assert rejected["has_mistake"] is False
        repository.save_grammar_explanation(
            grammar_key,
            "不含已撤销证据的讲解",
            prompt_version="grammar-explanation-v2",
            evidence_fingerprint="empty",
            evidence_refs=[],
        )
        # Idempotent means a network retry must not purge a valid regenerated cache.
        rejected_again = repository.reject_learning_event(event_id)
        assert rejected_again is not None
        assert rejected_again["mistake_count"] == 0
        assert rejected_again["explanation"] == "不含已撤销证据的讲解"

        restored = repository.unreject_learning_event(event_id)
        assert restored is not None
        assert restored["mistake_count"] == 1
        assert restored["latest_mistake"] == "買うておきます"

        assert repository.reject_learning_event(999_999_999) is None
        assert repository.unreject_learning_event(999_999_999) is None

        evidence = repository.grammar_evidence(grammar_key)
        assert evidence == [
            {
                "kind": "correction",
                "id": event_id,
                "original_fragment": "買うておきます",
                "replacement": "買っておきます",
                "reason_zh": "五段动词「買う」的て形是「買って」。",
                "created_at": correction_created_at,
            }
        ]

        # Deleting the correction must clean up the learning_event row too, or the
        # projection would keep counting evidence whose source no longer exists.
        assert repository.delete_chat_correction(int(correction["id"])) is True
        with engine.connect() as connection:
            remaining = connection.execute(
                text(
                    """SELECT count(*) FROM learning_event
                       WHERE source_table = 'chat_correction_item' AND source_id = :source_id"""
                ),
                {"source_id": correction_item_id},
            ).scalar_one()
        assert remaining == 0
        after_delete = repository.get_grammar_point(grammar_key)
        assert after_delete is not None
        assert after_delete["mistake_count"] == 0
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session_id})
            connection.execute(text("DELETE FROM grammar_point WHERE id = :id"), {"id": point_id})
        engine.dispose()


@pytest.mark.integration
def test_learning_event_failure_does_not_roll_back_a_completed_chat_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    grammar_key = f"test-event-failure-{uuid.uuid4().hex}"
    session_id = f"test-{uuid.uuid4()}"
    with engine.begin() as connection:
        point_id = connection.execute(
            text(
                """INSERT INTO grammar_point
                   (key, title_ja, title_zh, level, category, sort_order)
                   VALUES (:key, '～検証', '验证点', 'N5', '测试', 999999)
                   RETURNING id"""
            ),
            {"key": grammar_key},
        ).scalar_one()

    try:
        repository.create_chat_session(
            session_id=session_id,
            topic="事件失败隔离",
            starter_id=None,
            assistant_content="始めましょう。",
        )

        def fail_event_write(**_: Any) -> bool:
            raise RuntimeError("simulated event index failure")

        monkeypatch.setattr(repository, "_record_learning_event", fail_event_write)
        user, correction, assistant = repository.complete_chat_turn(
            session_id=session_id,
            user_content="読むています。",
            assistant_content="読んでいます。",
            correction={
                "corrected_text": "読んでいます。",
                "summary_zh": "て形",
                "items": [
                    {
                        "original": "読むています",
                        "replacement": "読んでいます",
                        "reason_zh": "て形",
                        "category": "grammar",
                        "grammar_key": grammar_key,
                    }
                ],
            },
        )

        assert user["content"] == "読むています。"
        assert correction is not None
        assert assistant["content"] == "読んでいます。"
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM chat_correction WHERE session_id = :session_id"),
                {"session_id": session_id},
            ).scalar_one() == 1
            assert connection.execute(
                text(
                    """SELECT count(*) FROM learning_event
                       WHERE source_table = 'chat_correction_item'
                         AND source_id = :source_id"""
                ),
                {"source_id": int(correction["items"][0]["id"])},
            ).scalar_one() == 0
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session_id})
            connection.execute(text("DELETE FROM grammar_point WHERE id = :id"), {"id": point_id})
        engine.dispose()


@pytest.mark.integration
def test_grammar_catalogue_keeps_unseen_levels_and_prioritizes_existing_evidence() -> None:
    """Learning history may reorder the compact catalogue but must never gate first
    discovery: an advanced user's first N4 mistake still needs its key in the prompt."""
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    repository.sync_grammar_catalogue()
    priority_key = f"test-catalogue-priority-{uuid.uuid4().hex}"
    try:
        baseline = repository.grammar_catalogue_for_prompt()
        assert {row[0] for row in GRAMMAR_CATALOGUE} <= {row[0] for row in baseline}
        assert {row[3] for row in baseline} >= {"N5", "N4"}

        with engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO grammar_point
                       (key, title_ja, title_zh, level, category, sort_order)
                       VALUES (:key, '～検証', '验证点', 'N4', '测试', 999999)"""
                ),
                {"key": priority_key},
            )
        repository.mark_grammar_encounter(priority_key, status="encountered", source="browse")

        reordered = repository.grammar_catalogue_for_prompt()
        assert reordered[0][0] == priority_key
        assert {row[0] for row in GRAMMAR_CATALOGUE} <= {row[0] for row in reordered}
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM grammar_point WHERE key = :key"), {"key": priority_key})
        engine.dispose()
