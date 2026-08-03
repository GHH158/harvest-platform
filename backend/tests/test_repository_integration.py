import os
import uuid

import pytest
from app import main
from app.config import Settings
from app.db import apply_schema, make_engine
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

        def reply(self, messages: list[dict[str, str]]) -> str:
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
