from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.asr import RecognizedWord
from app.config import Settings
from app.repository import Job
from app.worker import Worker


class PipelineRepository:
    def __init__(self, jobs: list[Job]) -> None:
        self.jobs = jobs
        self.next_job_id = max((job.id for job in jobs), default=0) + 1
        self.claimed: list[Job] = []
        self.processing: list[int] = []
        self.done: list[int] = []
        self.failed: list[tuple[int, int | None, str]] = []
        self.enqueued: list[Job] = []
        self.tokens: list[dict[str, Any]] | None = None
        self.video_assets: dict[str, Any] | None = None
        self.video_segments: list[dict[str, Any]] | None = None
        self.video_translations: list[str] | None = None
        self.reading_completion: dict[str, Any] | None = None
        self.shadowing_result: tuple[int, str, list[dict[str, Any]], float] | None = None
        self.shadowing_failure: tuple[int, str] | None = None

    def fail_exhausted_pending_jobs(self, *, max_attempts: int) -> int:
        return 0

    def claim_next_job(self, *, max_attempts: int) -> Job | None:
        if not self.jobs:
            return None
        job = self.jobs.pop(0)
        self.claimed.append(job)
        return job

    def mark_material_processing(self, material_id: int) -> None:
        self.processing.append(material_id)

    def mark_job_done(self, job_id: int) -> None:
        self.done.append(job_id)

    def mark_job_failed(self, job_id: int, material_id: int | None, message: str) -> None:
        self.failed.append((job_id, material_id, message))

    def enqueue_job(self, *, kind: str, material_id: int | None, payload: dict[str, Any]) -> int:
        job = Job(id=self.next_job_id, kind=kind, material_id=material_id, payload=payload, attempts=0)
        self.next_job_id += 1
        self.jobs.append(job)
        self.enqueued.append(job)
        return job.id

    def replace_tokens(self, material_id: int, tokens: list[dict[str, Any]]) -> None:
        self.tokens = tokens

    def complete_reading(self, **values: Any) -> None:
        self.reading_completion = values

    def store_video_assets(self, **values: Any) -> None:
        self.video_assets = values

    def replace_video_segments(self, material_id: int, segments: list[dict[str, Any]]) -> None:
        self.video_segments = segments

    def complete_video_translation(self, material_id: int, translations: list[str]) -> None:
        self.video_translations = translations

    def get_segment(self, segment_id: int) -> dict[str, Any] | None:
        return {"id": segment_id, "text_ja": "雨です。"}

    def complete_shadowing_attempt(
        self, attempt_id: int, transcript: str, diff: list[dict[str, Any]], score: float
    ) -> None:
        self.shadowing_result = attempt_id, transcript, diff, score

    def fail_shadowing_attempt(self, attempt_id: int, message: str) -> None:
        self.shadowing_failure = attempt_id, message


class StaticASR:
    def __init__(self, words: list[RecognizedWord] | None = None, error: str | None = None) -> None:
        self.words = words or []
        self.error = error

    def transcribe_words(self, _: str) -> list[RecognizedWord]:
        if self.error:
            raise RuntimeError(self.error)
        return self.words


def asr_job() -> Job:
    return Job(
        id=1,
        kind="asr",
        material_id=7,
        payload={"text": "雨です。", "audio_url": "https://media.example/reading.mp3"},
        attempts=1,
    )


def test_asr_success_keeps_ready_material_consumable() -> None:
    repository = PipelineRepository([asr_job()])
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    worker.asr = StaticASR([RecognizedWord("雨です。", 0, 1_000)])  # type: ignore[assignment]

    assert worker.run_one() is True

    assert repository.processing == []
    assert repository.failed == []
    assert repository.done == [1]
    assert repository.tokens


def test_low_coverage_asr_keeps_estimated_timeline_and_ready_status() -> None:
    repository = PipelineRepository([asr_job()])
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    worker.asr = StaticASR([RecognizedWord("猫", 0, 300)])  # type: ignore[assignment]

    assert worker.run_one() is True

    assert repository.processing == []
    assert repository.failed == []
    assert repository.done == [1]
    assert repository.tokens is None


def test_failed_asr_only_fails_enhancement_job() -> None:
    repository = PipelineRepository([asr_job()])
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    worker.asr = StaticASR(error="ASR unavailable")  # type: ignore[assignment]

    assert worker.run_one() is True

    assert repository.processing == []
    assert repository.failed == [(1, None, "ASR unavailable")]


class FakeVideoProcessor:
    def transcode_delivery(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"delivery")

    def extract_audio(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"audio")


class FakeStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str]] = []

    def upload_audio(self, local_path: Path, oss_key: str) -> str:
        self.uploads.append((local_path, oss_key))
        return self.public_url(oss_key)

    def public_url(self, oss_key: str) -> str:
        return f"https://media.example/{oss_key}"


class StaticLLM:
    def reply(self, messages: list[dict[str, str]]) -> str:
        sentences = json.loads(messages[-1]["content"])
        return json.dumps(["这是。" for _ in sentences], ensure_ascii=False)


class FakeTTS:
    def synthesize(self, *, text: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"audio")


class StaticVision:
    def extract_japanese(self, image_path: Path) -> str:
        return "雨です。"


def test_reading_pipeline_becomes_ready_before_optional_asr(
    monkeypatch: Any, tmp_path: Path
) -> None:
    initial = Job(id=1, kind="tts", material_id=7, payload={"text": "雨です。"}, attempts=1)
    repository = PipelineRepository([initial])
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.tts = FakeTTS()  # type: ignore[assignment]
    worker.storage = FakeStorage()  # type: ignore[assignment]
    worker.asr = StaticASR([RecognizedWord("雨です。", 0, 1_000)])  # type: ignore[assignment]
    monkeypatch.setattr("app.worker.audio_duration_ms", lambda _: 1_000)

    while worker.run_one():
        pass

    assert [job.kind for job in repository.claimed] == ["tts", "asr"]
    assert repository.processing == [7]
    assert repository.reading_completion is not None
    assert repository.tokens


def test_photo_pipeline_enters_reading_pipeline(monkeypatch: Any, tmp_path: Path) -> None:
    photo = tmp_path / "page.jpg"
    photo.write_bytes(b"photo")
    initial = Job(id=1, kind="vision", material_id=7, payload={"image_path": str(photo)}, attempts=1)
    repository = PipelineRepository([initial])
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.vision = StaticVision()  # type: ignore[assignment]
    worker.tts = FakeTTS()  # type: ignore[assignment]
    worker.storage = FakeStorage()  # type: ignore[assignment]
    worker.asr = StaticASR([RecognizedWord("雨です。", 0, 1_000)])  # type: ignore[assignment]
    monkeypatch.setattr("app.worker.audio_duration_ms", lambda _: 1_000)

    while worker.run_one():
        pass

    assert [job.kind for job in repository.claimed] == ["vision", "tts", "asr"]
    assert repository.processing == [7, 7]
    assert repository.reading_completion is not None
    assert repository.tokens


def test_video_pipeline_reaches_translation_completion(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    initial = Job(id=1, kind="transcode", material_id=7, payload={"source_path": str(source)}, attempts=1)
    repository = PipelineRepository([initial])
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.video = FakeVideoProcessor()  # type: ignore[assignment]
    worker.storage = FakeStorage()  # type: ignore[assignment]
    worker.asr = StaticASR([RecognizedWord("これは。", 0, 1_200)])  # type: ignore[assignment]
    worker.llm = StaticLLM()  # type: ignore[assignment]

    while worker.run_one():
        pass

    assert [job.kind for job in repository.claimed] == [
        "transcode",
        "upload_video",
        "asr_video",
        "translate_video",
    ]
    assert repository.processing == [7, 7, 7, 7]
    assert repository.failed == []
    assert repository.video_assets is not None
    assert repository.video_segments == [
        {"idx": 0, "text_ja": "これは。", "start_ms": 0, "end_ms": 1_200}
    ]
    assert repository.video_translations == ["这是。"]


def test_shadowing_failure_sets_attempt_failure(tmp_path: Path) -> None:
    audio = tmp_path / "attempt.m4a"
    audio.write_bytes(b"audio")
    job = Job(
        id=1,
        kind="shadowing",
        material_id=None,
        payload={"attempt_id": 9, "segment_id": 4, "audio_path": str(audio)},
        attempts=1,
    )
    repository = PipelineRepository([job])
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    worker.storage = FakeStorage()  # type: ignore[assignment]
    worker.asr = StaticASR(error="ASR unavailable")  # type: ignore[assignment]

    assert worker.run_one() is True

    assert repository.failed == [(1, None, "ASR unavailable")]
    assert repository.shadowing_failure == (9, "ASR unavailable")
