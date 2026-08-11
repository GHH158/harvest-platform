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
        # §17: the companion writer is retired, but everything it fed is not — the
        # projection, the backfill and the cascade trigger below all still read these
        # two tables, so the fixture goes in directly instead of through a method that
        # no longer exists.
        with engine.begin() as connection:
            question_id = int(
                connection.execute(
                    text(
                        """INSERT INTO companion_message (material_id, segment_id, role, content)
                           VALUES (:material_id, NULL, 'user', :content) RETURNING id"""
                    ),
                    {"material_id": material_id, "content": "这里为什么要用「ておく」？"},
                ).scalar_one()
            )
            point_id = connection.execute(
                text("SELECT id FROM grammar_point WHERE key = :key"), {"key": grammar_key}
            ).scalar_one()
            # Written twice on purpose: the (message_id, point_id) uniqueness is what
            # keeps one question from being counted as two encounters.
            for _ in range(2):
                connection.execute(
                    text(
                        """INSERT INTO companion_grammar_evidence (message_id, point_id)
                           VALUES (:message_id, :point_id) ON CONFLICT DO NOTHING"""
                    ),
                    {"message_id": question_id, "point_id": point_id},
                )
        question = {"id": question_id}

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
                       WHERE source_table = 'chat_correction_item' AND source_id = :source_id
                         AND subject_kind = 'grammar_point'"""
                    # One correction now carries two subjects (§5.11): the grammar
                    # association tested here, plus a correction_category event that
                    # exists even when the model gave no grammar_key.
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
                       WHERE source_table = 'chat_correction_item' AND source_id = :source_id
                         AND subject_kind = 'grammar_point'"""
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
                     " AND source_id = :source_id AND subject_kind = 'grammar_point'"),
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


@pytest.mark.integration
def test_vocabulary_saved_and_reviewed_events_dual_write_and_converge_on_delete() -> None:
    """§5.11 M1-B: a genuine new save fires vocabulary_saved (a merge-save does not);
    every review submission both appends an immutable vocabulary_review_attempt row and
    fires vocabulary_reviewed; deleting the word cascades to both event kinds."""
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    word = f"検証{uuid.uuid4().hex[:8]}"

    try:
        row, already_saved = repository.add_vocabulary(
            word=word, reading="けんしょう", meaning="验证", part_of_speech=None, context=None
        )
        assert already_saved is False
        vocabulary_id = int(row["id"])

        with engine.connect() as connection:
            saved_event = connection.execute(
                text(
                    """SELECT kind, subject_kind, subject_key, occurred_at, payload
                       FROM learning_event WHERE source_table = 'vocabulary' AND source_id = :id"""
                ),
                {"id": vocabulary_id},
            ).mappings().one()
        assert saved_event["kind"] == "vocabulary_saved"
        assert saved_event["subject_kind"] == "vocabulary_word"
        assert saved_event["subject_key"] == str(vocabulary_id)
        assert saved_event["payload"] == {"word": word, "reading": "けんしょう", "meaning": "验证"}

        # Re-saving the same word merges instead of inserting a new row, and must not
        # fire a second vocabulary_saved event for the same source_id.
        _, already_saved_again = repository.add_vocabulary(
            word=word, reading=None, meaning="验证（补充）", part_of_speech="动词", context=None
        )
        assert already_saved_again is True
        with engine.connect() as connection:
            saved_event_count = connection.execute(
                text(
                    "SELECT count(*) FROM learning_event WHERE source_table = 'vocabulary' AND source_id = :id"
                ),
                {"id": vocabulary_id},
            ).scalar_one()
        assert saved_event_count == 1

        updated = repository.record_vocabulary_review(vocabulary_id, correct=True)
        assert updated is not None
        assert updated["box"] == 2
        second = repository.record_vocabulary_review(vocabulary_id, correct=False)
        assert second is not None
        assert second["box"] == 1

        with engine.connect() as connection:
            review_attempts = connection.execute(
                text(
                    """SELECT correct, box_before, box_after FROM vocabulary_review_attempt
                       WHERE vocabulary_id = :id ORDER BY id"""
                ),
                {"id": vocabulary_id},
            ).mappings().all()
            reviewed_events = connection.execute(
                text(
                    """SELECT le.subject_key, le.occurred_at, le.payload, vra.created_at AS attempt_created_at
                       FROM learning_event le
                       JOIN vocabulary_review_attempt vra ON vra.id = le.source_id
                       WHERE le.source_table = 'vocabulary_review_attempt'
                       ORDER BY le.id"""
                ),
            ).mappings().all()
        assert [dict(row) for row in review_attempts] == [
            {"correct": True, "box_before": 1, "box_after": 2},
            {"correct": False, "box_before": 2, "box_after": 1},
        ]
        assert len(reviewed_events) == 2
        for event in reviewed_events:
            assert event["subject_key"] == str(vocabulary_id)
            # occurred_at is the review attempt's own timestamp, not learning_event's.
            assert event["occurred_at"] == event["attempt_created_at"]
        assert [event["payload"] for event in reviewed_events] == [
            {"correct": True, "box_before": 1, "box_after": 2},
            {"correct": False, "box_before": 2, "box_after": 1},
        ]

        assert repository.delete_vocabulary(vocabulary_id) is True
        with engine.connect() as connection:
            remaining_attempts = connection.execute(
                text("SELECT count(*) FROM vocabulary_review_attempt WHERE vocabulary_id = :id"),
                {"id": vocabulary_id},
            ).scalar_one()
            remaining_saved_events = connection.execute(
                text("SELECT count(*) FROM learning_event WHERE source_table = 'vocabulary' AND source_id = :id"),
                {"id": vocabulary_id},
            ).scalar_one()
            remaining_reviewed_events = connection.execute(
                text(
                    """SELECT count(*) FROM learning_event
                       WHERE source_table = 'vocabulary_review_attempt'
                         AND subject_key = :subject_key"""
                ),
                {"subject_key": str(vocabulary_id)},
            ).scalar_one()
        assert remaining_attempts == 0
        assert remaining_saved_events == 0
        assert remaining_reviewed_events == 0
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM vocabulary WHERE word = :word"), {"word": word})
        engine.dispose()


@pytest.mark.integration
def test_shadowing_completed_event_uses_submission_time_and_score_only_payload() -> None:
    """§5.11 M1-B: occurred_at is when the recording was submitted, not when scoring
    finished; payload never carries audio_path or asr_text, only the derived score."""
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    material_id, tts_job_id = repository.create_material_with_job(
        title="M1-B shadowing event test",
        source_type="paste",
        source_ref=None,
        job_kind="tts",
        payload={"text": "雨です。"},
    )
    shadowing_job_id: int | None = None
    try:
        repository.complete_reading(
            material_id=material_id,
            local_path="/tmp/m1b-shadowing.mp3",
            oss_key="materials/test/m1b-shadowing.mp3",
            bytes_count=100,
            duration_ms=1_000,
            segments=[{"idx": 0, "text_ja": "雨です。", "start_ms": 0, "end_ms": 1_000}],
        )
        segment_id = repository.get_segments(material_id)[0]["id"]
        attempt_id, shadowing_job_id = repository.create_shadowing_submission(segment_id, "/private/rec.m4a")
        submitted_at = repository.get_shadowing_attempt(attempt_id)["created_at"]

        repository.complete_shadowing_attempt(
            attempt_id,
            "雨ですね、とても静かです。",
            [{"word": "雨", "match": True}],
            0.83,
        )

        with engine.connect() as connection:
            event = connection.execute(
                text(
                    """SELECT kind, subject_kind, subject_key, occurred_at, payload
                       FROM learning_event WHERE source_table = 'shadowing_attempt' AND source_id = :id"""
                ),
                {"id": attempt_id},
            ).mappings().one()
        assert event["kind"] == "shadowing_completed"
        assert event["subject_kind"] == "segment"
        assert event["subject_key"] == str(segment_id)
        assert event["occurred_at"] == submitted_at
        assert event["payload"] == {"score": pytest.approx(0.83)}
        assert "audio_path" not in event["payload"]
        assert "asr_text" not in event["payload"]

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM job WHERE id = :job_id"), {"job_id": shadowing_job_id})
        shadowing_job_id = None
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM material WHERE id = :id"), {"id": material_id})
        with engine.connect() as connection:
            remaining = connection.execute(
                text("SELECT count(*) FROM learning_event WHERE source_table = 'shadowing_attempt' AND source_id = :id"),
                {"id": attempt_id},
            ).scalar_one()
        assert remaining == 0
        material_id = None
    finally:
        with engine.begin() as connection:
            if shadowing_job_id is not None:
                connection.execute(text("DELETE FROM job WHERE id = :job_id"), {"job_id": shadowing_job_id})
            if material_id is not None:
                connection.execute(text("DELETE FROM material WHERE id = :id"), {"id": material_id})
            connection.execute(text("DELETE FROM job WHERE id = :job_id"), {"job_id": tts_job_id})
        engine.dispose()


@pytest.mark.integration
def test_vocabulary_and_shadowing_event_failures_do_not_block_the_main_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    word = f"検証{uuid.uuid4().hex[:8]}"

    def fail_event_write(**_: Any) -> bool:
        raise RuntimeError("simulated event index failure")

    monkeypatch.setattr(repository, "_record_learning_event", fail_event_write)
    try:
        row, already_saved = repository.add_vocabulary(
            word=word, reading=None, meaning="验证", part_of_speech=None, context=None
        )
        assert already_saved is False
        vocabulary_id = int(row["id"])

        updated = repository.record_vocabulary_review(vocabulary_id, correct=True)
        assert updated is not None
        assert updated["box"] == 2
        with engine.connect() as connection:
            attempt_count = connection.execute(
                text("SELECT count(*) FROM vocabulary_review_attempt WHERE vocabulary_id = :id"),
                {"id": vocabulary_id},
            ).scalar_one()
        assert attempt_count == 1
        with engine.connect() as connection:
            event_count = connection.execute(
                text(
                    """SELECT count(*) FROM learning_event
                       WHERE (source_table = 'vocabulary' OR source_table = 'vocabulary_review_attempt')
                         AND subject_key = :subject_key"""
                ),
                {"subject_key": str(vocabulary_id)},
            ).scalar_one()
        assert event_count == 0
        repository.backfill_learning_events()
        with engine.connect() as connection:
            repaired_count = connection.execute(
                text(
                    """SELECT count(*) FROM learning_event
                       WHERE (source_table = 'vocabulary' OR source_table = 'vocabulary_review_attempt')
                         AND subject_key = :subject_key"""
                ),
                {"subject_key": str(vocabulary_id)},
            ).scalar_one()
        assert repaired_count == 2
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM vocabulary WHERE word = :word"), {"word": word})
        engine.dispose()


@pytest.mark.integration
def test_backfill_covers_real_vocabulary_attempts_and_completed_shadowing() -> None:
    """§5.11: no reviews are fabricated from legacy aggregate counters, while every
    row that actually exists in vocabulary_review_attempt is a real replayable fact."""
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    word = f"回填{uuid.uuid4().hex[:8]}"
    material_id, tts_job_id = repository.create_material_with_job(
        title="M1-B backfill test",
        source_type="paste",
        source_ref=None,
        job_kind="tts",
        payload={"text": "雨です。"},
    )
    shadowing_job_id: int | None = None
    try:
        # Simulate pre-existing legacy rows written before this adapter existed, by
        # inserting directly and skipping the repository methods that dual-write.
        with engine.begin() as connection:
            vocabulary_id = connection.execute(
                text(
                    """INSERT INTO vocabulary (word, reading, meaning)
                       VALUES (:word, '回填', '回填测试') RETURNING id"""
                ),
                {"word": word},
            ).scalar_one()

        repository.complete_reading(
            material_id=material_id,
            local_path="/tmp/m1b-backfill.mp3",
            oss_key="materials/test/m1b-backfill.mp3",
            bytes_count=100,
            duration_ms=1_000,
            segments=[{"idx": 0, "text_ja": "雨です。", "start_ms": 0, "end_ms": 1_000}],
        )
        segment_id = repository.get_segments(material_id)[0]["id"]
        attempt_id, shadowing_job_id = repository.create_shadowing_submission(segment_id, "/private/legacy.m4a")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """UPDATE shadowing_attempt
                       SET status = 'ready', score = 0.5, asr_text = '雨ですね。'
                       WHERE id = :id"""
                ),
                {"id": attempt_id},
            )
            review_attempt_id = connection.execute(
                text(
                    """INSERT INTO vocabulary_review_attempt (vocabulary_id, correct, box_before, box_after)
                       VALUES (:vocabulary_id, true, 1, 2) RETURNING id"""
                ),
                {"vocabulary_id": vocabulary_id},
            ).scalar_one()

        touched = repository.backfill_learning_events()
        assert isinstance(touched, list)

        with engine.connect() as connection:
            vocabulary_saved_count = connection.execute(
                text("SELECT count(*) FROM learning_event WHERE source_table = 'vocabulary' AND source_id = :id"),
                {"id": vocabulary_id},
            ).scalar_one()
            shadowing_completed_count = connection.execute(
                text(
                    "SELECT count(*) FROM learning_event WHERE source_table = 'shadowing_attempt' AND source_id = :id"
                ),
                {"id": attempt_id},
            ).scalar_one()
            reviewed_count = connection.execute(
                text(
                    "SELECT count(*) FROM learning_event WHERE source_table = 'vocabulary_review_attempt' AND source_id = :id"
                ),
                {"id": review_attempt_id},
            ).scalar_one()
        assert vocabulary_saved_count == 1
        assert shadowing_completed_count == 1
        assert reviewed_count == 1

        # Idempotent: running it again must not duplicate either backfilled kind.
        repository.backfill_learning_events()
        with engine.connect() as connection:
            vocabulary_saved_count_again = connection.execute(
                text("SELECT count(*) FROM learning_event WHERE source_table = 'vocabulary' AND source_id = :id"),
                {"id": vocabulary_id},
            ).scalar_one()
            shadowing_completed_count_again = connection.execute(
                text(
                    "SELECT count(*) FROM learning_event WHERE source_table = 'shadowing_attempt' AND source_id = :id"
                ),
                {"id": attempt_id},
            ).scalar_one()
            reviewed_count_again = connection.execute(
                text(
                    "SELECT count(*) FROM learning_event "
                    "WHERE source_table = 'vocabulary_review_attempt' AND source_id = :id"
                ),
                {"id": review_attempt_id},
            ).scalar_one()
        assert vocabulary_saved_count_again == 1
        assert shadowing_completed_count_again == 1
        assert reviewed_count_again == 1
    finally:
        with engine.begin() as connection:
            if shadowing_job_id is not None:
                connection.execute(text("DELETE FROM job WHERE id = :job_id"), {"job_id": shadowing_job_id})
            connection.execute(text("DELETE FROM material WHERE id = :id"), {"id": material_id})
            connection.execute(text("DELETE FROM job WHERE id = :job_id"), {"job_id": tts_job_id})
            connection.execute(text("DELETE FROM vocabulary WHERE word = :word"), {"word": word})
        engine.dispose()


def _correction(original: str, replacement: str, category: str, grammar_key: str | None = None):
    return {
        "corrected_text": replacement,
        "summary_zh": "总结",
        "items": [
            {
                "original": original,
                "replacement": replacement,
                "reason_zh": "理由",
                "category": category,
                **({"grammar_key": grammar_key} if grammar_key else {}),
            }
        ],
    }


@pytest.mark.integration
def test_backfill_indexes_every_correction_category() -> None:
    """Legacy corrections written before the category subject existed must become
    events too, otherwise the fact layer keeps only grammar-shaped mistakes."""
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    session_id = f"test-{uuid.uuid4()}"
    try:
        repository.create_chat_session(
            session_id=session_id, topic="回填", starter_id=None, assistant_content="始めましょう。"
        )
        # Simulate legacy rows: correction items with no learning_event at all.
        with engine.begin() as connection:
            for index in range(3):
                message_id = connection.execute(
                    text(
                        """INSERT INTO chat_message (session_id, role, content)
                           VALUES (:session_id, 'user', :content) RETURNING id"""
                    ),
                    {"session_id": session_id, "content": f"旧文{index}"},
                ).scalar_one()
                correction_id = connection.execute(
                    text(
                        """INSERT INTO chat_correction
                           (session_id, user_message_id, original_text, corrected_text, summary_zh)
                           VALUES (:session_id, :message_id, '旧文', '新文', '总结') RETURNING id"""
                    ),
                    {"session_id": session_id, "message_id": message_id},
                ).scalar_one()
                connection.execute(
                    text(
                        """INSERT INTO chat_correction_item
                           (correction_id, idx, original_fragment, replacement, reason_zh, category)
                           VALUES (:correction_id, 0, '旧文', '新文', '理由', 'orthography')"""
                    ),
                    {"correction_id": correction_id},
                )

        repository.backfill_learning_events()
        with engine.connect() as connection:
            backfilled = connection.execute(
                text(
                    """SELECT count(*) FROM learning_event
                       WHERE subject_kind = 'correction_category' AND subject_key = 'orthography'
                         AND backfilled = true"""
                )
            ).scalar_one()
        assert backfilled == 3

        # Running the whole startup path again changes nothing.
        repository.backfill_learning_events()
        with engine.connect() as connection:
            again = connection.execute(
                text(
                    """SELECT count(*) FROM learning_event
                       WHERE subject_kind = 'correction_category' AND subject_key = 'orthography'"""
                )
            ).scalar_one()
        assert again == 3
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session_id})
        engine.dispose()


@pytest.mark.integration
def test_decision_trace_records_success_and_locates_the_failing_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5.13 / M1 pass condition: a silent background path must leave enough metadata
    to find the entry point, the rule version and the stage that broke."""
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    session_id = f"test-{uuid.uuid4()}"
    material_id: int | None = None
    with engine.begin() as connection:
        # decision_trace is global diagnostics, not scoped to a session, so other
        # tests in the same database leave rows behind. Start from a known state.
        connection.execute(text("DELETE FROM decision_trace"))
    try:
        repository.create_chat_session(
            session_id=session_id, topic="trace", starter_id=None, assistant_content="始めましょう。"
        )
        repository.complete_chat_turn(
            session_id=session_id,
            user_content="随时",
            assistant_content="いつでも",
            correction=_correction("随时", "いつでも", "word_choice"),
            decision_context={
                "model_provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "prompt_version": "chat-turn-v1",
                "attempted_providers": ["dashscope", "deepseek"],
            },
        )

        indexed = repository.list_decision_traces(call_source="chat_correction_index")
        assert len(indexed) == 1
        assert indexed[0]["status"] == "ok"
        assert indexed[0]["failure_stage"] is None
        assert indexed[0]["rule_version"] == "learning-event-v1"
        assert indexed[0]["model_provider"] == "deepseek"
        assert indexed[0]["model_name"] == "deepseek-v4-flash"
        assert indexed[0]["prompt_version"] == "chat-turn-v1"
        assert indexed[0]["detail"] == {
            "indexed": 1,
            "expected": 1,
            "attempted_providers": ["dashscope", "deepseek"],
        }
        assert indexed[0]["duration_ms"] >= 0

        # Now break an indexing path and confirm the failure is attributable to a
        # stage. This check has moved twice: the memory rebuild played the role until it
        # was removed on 2026-08-09, then the companion grammar index until §17 retired
        # it (2026-08-12). It now rides on the correction index — the remaining silent
        # path whose only account of itself is the trace (§5.13).
        def fail_mark(*_: Any, **__: Any) -> None:
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(repository, "mark_grammar_encounter", fail_mark)
        # Unlike the retired companion path, this one swallows the projection failure —
        # a correction that was saved must not look failed to the learner just because
        # the skeleton projection broke. The trace is the only place it surfaces.
        repository.complete_chat_turn(
            session_id=session_id,
            user_content="読むています",
            assistant_content="読んでいます",
            # A grammar_key is what makes this reach the skeleton projection at all —
            # a category-only correction never calls mark_grammar_encounter.
            correction=_correction("読むています", "読んでいます", "grammar", grammar_key="verb-te"),
        )

        failed = repository.list_decision_traces(status="failed")
        assert len(failed) == 1
        assert failed[0]["call_source"] == "chat_correction_index"
        assert failed[0]["failure_stage"] == "project_grammar"
        # The successful first turn's trace is still there, untouched.
        assert len(repository.list_decision_traces(call_source="chat_correction_index")) == 2
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session_id})
            if material_id is not None:
                connection.execute(text("DELETE FROM material WHERE id = :id"), {"id": material_id})
            connection.execute(text("DELETE FROM decision_trace"))
            # §11.6: deleting the material removes the companion evidence and, via the
            # trigger, its learning_event — but the grammar_encounter projection is
            # rebuilt by the application layer, which nothing here calls. The leftover
            # verb-te row then sorted ahead of another test's N4 point on the next run
            # against the same database.
            connection.execute(text("DELETE FROM grammar_encounter"))
        engine.dispose()


@pytest.mark.integration
def test_decision_trace_never_stores_the_learner_text_and_expires() -> None:
    """§5.13 privacy boundary and retention: the trace holds references and counts,
    not the sentence the learner wrote, and old rows are pruned at startup."""
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    session_id = f"test-{uuid.uuid4()}"
    secret = f"私密句子{uuid.uuid4().hex}"
    with engine.begin() as connection:
        # decision_trace is global diagnostics, not scoped to a session, so other
        # tests in the same database leave rows behind. Start from a known state.
        connection.execute(text("DELETE FROM decision_trace"))
    try:
        repository.create_chat_session(
            session_id=session_id, topic="隐私", starter_id=None, assistant_content="始めましょう。"
        )
        repository.complete_chat_turn(
            session_id=session_id,
            user_content=secret,
            assistant_content="修正",
            correction=_correction(secret, "修正", "grammar"),
        )

        with engine.connect() as connection:
            dumped = connection.execute(
                text("SELECT reason, detail::text, evidence_refs::text FROM decision_trace")
            ).mappings().all()
        assert dumped
        for row in dumped:
            for value in row.values():
                assert secret not in str(value)

        # Retention: a row older than the window goes, a fresh one stays.
        with engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO decision_trace
                       (call_source, status, reason, duration_ms, created_at)
                       VALUES ('learner_memory_rebuild', 'ok', '旧记录', 1,
                               now() - make_interval(days => 31))"""
                )
            )
        before = len(repository.list_decision_traces(limit=200))
        assert repository.prune_decision_traces() == 1
        assert len(repository.list_decision_traces(limit=200)) == before - 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session_id})
            connection.execute(text("DELETE FROM decision_trace"))
        engine.dispose()


@pytest.mark.integration
def test_trace_write_failure_cannot_break_the_operation_it_observes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5.13: observability must not become a new failure mode for the thing it
    observes — a broken trace would otherwise take the degradation gate down too."""
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    word = f"検証{uuid.uuid4().hex[:8]}"
    with engine.begin() as connection:
        # decision_trace is global diagnostics, not scoped to a session, so other
        # tests in the same database leave rows behind. Start from a known state.
        connection.execute(text("DELETE FROM decision_trace"))
    try:
        # A malformed trace (duration_ms is NOT NULL) makes the insert fail inside
        # the recorder. It must absorb that itself and return normally.
        repository._record_decision_trace(
            call_source="learner_memory_rebuild",
            status="ok",
            reason="故意写坏的 trace",
            duration_ms=None,  # type: ignore[arg-type]
        )
        assert repository.list_decision_traces() == []

        # With tracing broken for every call, the observed operation still succeeds
        # and its learning event is still indexed.
        original = Repository._record_decision_trace
        monkeypatch.setattr(
            Repository,
            "_record_decision_trace",
            lambda self, **kwargs: original(self, **{**kwargs, "duration_ms": None}),
        )
        row, already_saved = repository.add_vocabulary(
            word=word, reading=None, meaning="验证", part_of_speech=None, context=None
        )

        assert already_saved is False
        assert row["word"] == word
        with engine.connect() as connection:
            indexed = connection.execute(
                text("SELECT count(*) FROM learning_event WHERE source_table = 'vocabulary' AND source_id = :id"),
                {"id": int(row["id"])},
            ).scalar_one()
        assert indexed == 1
        assert repository.list_decision_traces() == []
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM vocabulary WHERE word = :word"), {"word": word})
            connection.execute(text("DELETE FROM decision_trace"))
        engine.dispose()


@pytest.mark.integration
def test_same_register_version_round_trips_through_the_correction_store() -> None:
    """§5.6 (2026-08-10). The parsing rules have unit tests; this pins the storage path,
    because a nullable column that is written but never read back is the kind of thing
    that looks fine until the card is empty on the phone."""

    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")

    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    repository = Repository(engine)
    session_id = f"register-{uuid.uuid4()}"
    _, correction, _ = repository.complete_chat_turn(
        session_id=session_id,
        user_content="話したいことが話さない",
        assistant_content="そうですか。",
        correction={
            "needed": True,
            "corrected_text": "話したいことが話せません",
            "summary_zh": "可能形の否定を使う",
            "items": [
                {
                    "original": "話さない",
                    "replacement": "話せません",
                    "same_register_replacement": "話せない",
                    "reason_zh": "需要可能态否定；你原句是简体，这里给的是丁宁体",
                    "category": "grammar",
                    "grammar_key": None,
                },
                {
                    "original": "話したいこと",
                    "replacement": "言いたいこと",
                    "reason_zh": "自然な言い回し",
                    "category": "naturalness",
                    "grammar_key": None,
                },
            ],
        },
        create_session_topic="register round trip",
    )
    try:
        assert correction is not None
        assert correction["items"][0]["same_register_replacement"] == "話せない"
        # Unchanged register stays null rather than repeating the replacement.
        assert correction["items"][1]["same_register_replacement"] is None

        listed = repository.chat_corrections(session_id=session_id, limit=10)
        assert listed[0]["items"][0]["same_register_replacement"] == "話せない"
        assert listed[0]["items"][1]["same_register_replacement"] is None
    finally:
        repository.delete_chat_session(session_id)


def _collection_repo() -> tuple[Repository, Any]:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")
    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    return Repository(engine), engine


@pytest.mark.integration
def test_deleting_a_material_converges_everything_hanging_off_it() -> None:
    """§15.7. `DELETE /materials` did not exist before 2026-08-10 — writing tests that day
    meant deleting materials with raw SQL. The database side is one statement because five
    foreign keys cascade and §4.3's triggers follow them; this pins that it stays true."""

    repository, engine = _collection_repo()
    material_id, job_id = repository.create_material_with_job(
        title="delete me",
        source_type="paste",
        source_ref=None,
        job_kind="tts",
        payload={"text": "消える。"},
    )
    repository.complete_reading(
        material_id=material_id,
        local_path="/tmp/delete-me.mp3",
        oss_key="materials/delete-me.mp3",
        bytes_count=10,
        duration_ms=1_000,
        segments=[{"idx": 0, "text_ja": "消える。", "start_ms": 0, "end_ms": 1_000}],
    )
    segment_id = int(repository.get_segments(material_id)[0]["id"])
    # §17: inserted directly — the writer is retired but the table (and this cascade)
    # still hold the historical rows, which is exactly what must converge on delete.
    with engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO companion_message (material_id, segment_id, role, content)
                   VALUES (:material_id, :segment_id, 'user', '这句什么意思')"""
            ),
            {"material_id": material_id, "segment_id": segment_id},
        )
    repository.save_playback_state(material_id, 500)

    assert repository.delete_material(material_id) is True

    with engine.connect() as connection:
        for table, column in (
            ("segment", "material_id"),
            ("companion_message", "material_id"),
            ("job", "material_id"),
            ("media_asset", "material_id"),
            ("material_playback_state", "material_id"),
        ):
            left = connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :id"), {"id": material_id}
            ).scalar_one()
            assert left == 0, f"{table} still has rows"
        orphan_events = connection.execute(
            text(
                """SELECT count(*) FROM learning_event
                   WHERE source_table IN ('companion_message', 'chat_correction_item')
                     AND source_id = :job_id"""
            ),
            {"job_id": job_id},
        ).scalar_one()
        assert orphan_events == 0
    # Deleting again is a 404 for the caller, not an error here.
    assert repository.delete_material(material_id) is False


@pytest.mark.integration
def test_deleting_a_material_cascades_questions_and_detaches_chat_sessions() -> None:
    """§16. `reading_question` rows are worthless without the material they were flagged
    on, so they cascade. A chat session that already happened is not — it only loses the
    "which lesson" label, which is why that foreign key is SET NULL rather than CASCADE."""

    repository, engine = _collection_repo()
    material_id, _ = repository.create_material_with_job(
        title="delete me too",
        source_type="paste",
        source_ref=None,
        job_kind="tts",
        payload={"text": "消える。"},
    )
    question = repository.add_reading_question(material_id=material_id, excerpt="消える")
    session, _ = repository.create_chat_session(
        session_id=f"test-{question['id']}",
        topic="delete me too",
        starter_id=None,
        assistant_content="わかりました。",
        material_id=material_id,
    )

    assert repository.delete_material(material_id) is True

    with engine.connect() as connection:
        remaining_questions = connection.execute(
            text("SELECT count(*) FROM reading_question WHERE material_id = :id"), {"id": material_id}
        ).scalar_one()
        assert remaining_questions == 0
        session_row = connection.execute(
            text("SELECT material_id FROM chat_session WHERE id = :id"), {"id": session["id"]}
        ).mappings().one()
        assert session_row["material_id"] is None
        message_count = connection.execute(
            text("SELECT count(*) FROM chat_message WHERE session_id = :id"), {"id": session["id"]}
        ).scalar_one()
        assert message_count == 1
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM chat_session WHERE id = :id"), {"id": session["id"]})


@pytest.mark.integration
def test_collection_sections_carry_the_same_fields_as_library_materials() -> None:
    """§15.5: sections come back through `list_materials`, so the player gets the delivery
    keys and job fields it already relies on. A second hand-written query would drift."""

    repository, engine = _collection_repo()
    collection = repository.create_collection("敬語レッスン")
    collection_id = int(collection["id"])
    ids: list[int] = []
    try:
        for index in range(3):
            material_id, _ = repository.create_material_with_job(
                title=f"第 {index + 1} 节",
                source_type="file",
                source_ref=None,
                job_kind="transcode",
                payload={},
            )
            ids.append(material_id)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """UPDATE material
                           SET collection_id = :collection_id,
                               collection_index = :index,
                               source_offset_ms = :offset,
                               duration_ms = 300000,
                               kind = 'video'
                           WHERE id = :id"""
                    ),
                    {
                        "collection_id": collection_id,
                        "index": index,
                        "offset": index * 300_000,
                        "id": material_id,
                    },
                )

        sections = repository.collection_sections(collection_id)
        # Ordered by section number, not by date.
        assert [section["collection_index"] for section in sections] == [0, 1, 2]
        assert [int(section["id"]) for section in sections] == ids
        # The fields the client depends on are present, not just the bare row.
        for key in ("audio_oss_key", "video_oss_key", "current_job_id", "thumbnail_local_path"):
            assert key in sections[0]
        assert sections[2]["source_offset_ms"] == 600_000

        listed = next(
            row for row in repository.collections() if int(row["id"]) == collection_id
        )
        # Derived on read (§15.5) — nothing aggregate is stored on the collection.
        assert listed["section_count"] == 3
        assert listed["ready_count"] == 0
        assert listed["total_duration_ms"] == 900_000

        assert repository.delete_collection(collection_id) is True
        with engine.connect() as connection:
            left = connection.execute(
                text("SELECT count(*) FROM material WHERE id = ANY(:ids)"), {"ids": ids}
            ).scalar_one()
        # Sections cascade from the collection (§15.7).
        assert left == 0
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM material WHERE id = ANY(:ids)"), {"ids": ids})
            connection.execute(
                text("DELETE FROM material_collection WHERE id = :id"), {"id": collection_id}
            )


@pytest.mark.integration
def test_collection_detail_and_list_return_the_same_shape() -> None:
    """§15.5. They did not at first: the detail endpoint returned the bare row without the
    counts, so the phone's model would have failed to decode on the very first open. Caught
    by inspecting the live response, not by a green suite — hence this test."""

    repository, engine = _collection_repo()
    collection = repository.create_collection("shape check")
    collection_id = int(collection["id"])
    try:
        listed = next(row for row in repository.collections() if int(row["id"]) == collection_id)
        detail = repository.get_collection(collection_id)
        assert detail is not None
        assert set(detail.keys()) == set(listed.keys())
        for key in ("section_count", "ready_count", "total_duration_ms"):
            assert key in detail
        assert detail["section_count"] == 0
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM material_collection WHERE id = :id"), {"id": collection_id}
            )
