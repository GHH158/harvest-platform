import os

import pytest
from app.config import Settings
from app.db import apply_schema, make_engine
from app.repository import RESUME_MAX_RATIO, RESUME_MIN_RATIO, Repository
from sqlalchemy import text


def _repository() -> Repository:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")
    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    return Repository(engine)


def _ready_material(
    repository: Repository, *, kind: str, duration_ms: int, sentences: int = 3
) -> int:
    material_id, _ = repository.create_material_with_job(
        title=f"resume {kind}",
        source_type="paste",
        source_ref=None,
        job_kind="tts",
        payload={"text": "テスト。"},
    )
    step = duration_ms // max(1, sentences)
    segments = [
        {
            "idx": index,
            "text_ja": f"文 {index}。",
            "start_ms": index * step,
            "end_ms": (index + 1) * step,
        }
        for index in range(sentences)
    ]
    repository.complete_reading(
        material_id=material_id,
        local_path=f"/tmp/resume-{kind}.mp3",
        oss_key=f"materials/resume/{kind}.mp3",
        bytes_count=100,
        duration_ms=duration_ms,
        segments=segments,
    )
    if kind != "reading":
        with repository.engine.begin() as connection:
            connection.execute(
                text("UPDATE material SET kind = :kind WHERE id = :id"),
                {"kind": kind, "id": material_id},
            )
    return material_id


def _clear(repository: Repository) -> None:
    """The hint is a query over the whole database, so these tests need a clean slate."""

    with repository.engine.begin() as connection:
        connection.execute(text("DELETE FROM material"))
        connection.execute(text("DELETE FROM grammar_encounter"))


def test_ratio_window_is_the_documented_one() -> None:
    """§5.18 fixed these from real data: three of four saved positions sat at 85–88%
    (finished) and one at 7% (actually interrupted)."""

    assert RESUME_MIN_RATIO == 0.02
    assert RESUME_MAX_RATIO == 0.80


@pytest.mark.integration
def test_nothing_to_say_returns_nothing() -> None:
    repository = _repository()
    _clear(repository)
    try:
        assert repository.resume_hint() is None
    finally:
        _clear(repository)


@pytest.mark.integration
def test_a_material_stopped_in_the_middle_is_offered_with_its_position() -> None:
    repository = _repository()
    _clear(repository)
    try:
        material_id = _ready_material(repository, kind="reading", duration_ms=100_000, sentences=10)
        # 40% through: past the "opened and backed out" floor, well under the "finished"
        # ceiling. Sentence 5 starts at 40_000ms, so the position lands exactly on it.
        repository.save_playback_state(material_id, 40_000)

        hint = repository.resume_hint()
        assert hint is not None
        assert hint["kind"] == "material"
        assert hint["material_id"] == material_id
        assert hint["material_kind"] == "reading"
        assert hint["position_ms"] == 40_000
        # Reading counts sentences; a timestamp is a strange unit for an article (§5.18).
        assert hint["sentence_number"] == 5
        # No completion figure anywhere in the payload: §4.2 says playback position is
        # media resumption, not progress, so the ratio must not reach the client.
        assert "progress" not in hint
        assert "ratio" not in hint
        assert "percent" not in hint
    finally:
        _clear(repository)


@pytest.mark.integration
def test_video_reports_a_timestamp_and_no_sentence_number() -> None:
    repository = _repository()
    _clear(repository)
    try:
        material_id = _ready_material(repository, kind="video", duration_ms=600_000, sentences=10)
        repository.save_playback_state(material_id, 43_050)

        hint = repository.resume_hint()
        assert hint is not None
        assert hint["material_kind"] == "video"
        assert hint["position_ms"] == 43_050
        assert hint["sentence_number"] is None
    finally:
        _clear(repository)


@pytest.mark.integration
def test_finished_and_barely_started_materials_are_not_offered() -> None:
    """The two ends of the window. 88% is the real-data case that made the ceiling 80%
    rather than 90%: reminding you about something you finished is just nagging."""

    repository = _repository()
    _clear(repository)
    try:
        finished = _ready_material(repository, kind="reading", duration_ms=100_000)
        repository.save_playback_state(finished, 88_000)
        assert repository.resume_hint() is None

        _clear(repository)
        barely = _ready_material(repository, kind="reading", duration_ms=100_000)
        repository.save_playback_state(barely, 1_000)
        assert repository.resume_hint() is None
    finally:
        _clear(repository)


@pytest.mark.integration
def test_an_interrupted_material_wins_over_a_grammar_point() -> None:
    repository = _repository()
    _clear(repository)
    repository.sync_grammar_catalogue()
    try:
        repository.mark_grammar_encounter("verb-te", status="encountered", source="companion")
        assert repository.resume_hint()["kind"] == "grammar"

        material_id = _ready_material(repository, kind="reading", duration_ms=100_000)
        repository.save_playback_state(material_id, 30_000)
        # §5.18 priority: something you can resume right now beats something to review.
        assert repository.resume_hint()["kind"] == "material"
    finally:
        _clear(repository)


@pytest.mark.integration
def test_only_encountered_points_are_offered_never_understood_ones() -> None:
    """An understood point resurfacing is not something to nudge about, and §5.10 forbids
    automation quietly downgrading that state."""

    repository = _repository()
    _clear(repository)
    repository.sync_grammar_catalogue()
    try:
        repository.mark_grammar_encounter("verb-te", status="understood", manual=True)
        assert repository.resume_hint() is None

        repository.mark_grammar_encounter("particle-wa", status="encountered", source="companion")
        hint = repository.resume_hint()
        assert hint is not None
        assert hint["kind"] == "grammar"
        assert hint["grammar_key"] == "particle-wa"
        assert hint["title_ja"]
        assert hint["title_zh"]
    finally:
        _clear(repository)
