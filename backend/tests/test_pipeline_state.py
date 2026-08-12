from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.asr import RecognizedWord
from app.config import Settings
from app.repository import Job
from app.voice import ExtractedVoiceSample
from app.worker import Worker


class PipelineRepository:
    def __init__(self, jobs: list[Job]) -> None:
        self.jobs = jobs
        self.next_job_id = max((job.id for job in jobs), default=0) + 1
        self.claimed: list[Job] = []
        self.processing: list[int] = []
        self.downloaded: list[int] = []
        self.done: list[int] = []
        self.failed: list[tuple[int, int | None, str]] = []
        self.enqueued: list[Job] = []
        self.transcode_payload: dict[str, Any] | None = None
        self.tokens: list[dict[str, Any]] | None = None
        self.video_assets: dict[str, Any] | None = None
        self.downloaded_video_assets: list[tuple[int, dict[str, Any]]] = []
        self.video_segments: list[dict[str, Any]] | None = None
        self.video_ready: list[int] = []
        self.translation_batches: list[tuple[int, int]] = []
        self.already_translated: set[int] = set()
        self.segment_translations: list[str] | None = None
        self.reading_completion: dict[str, Any] | None = None
        self.reading_segments: list[dict[str, Any]] = []
        self.shadowing_result: tuple[int, str, list[dict[str, Any]], float] | None = None
        self.shadowing_failure: tuple[int, str] | None = None
        self.voice_profile: tuple[str, str] | None = None
        self.job_payload_updates: tuple[int, dict[str, Any]] | None = None
        self.updated_title: tuple[int, str] | None = None
        # Section ids that a previous (interrupted) pass already cut, so `_split_video`
        # must skip them instead of re-encoding.
        self.already_cut: set[int] = set()

    def material_cut_is_done(self, material_id: int) -> bool:
        return material_id in self.already_cut

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

    def mark_material_downloaded(self, material_id: int, duration_ms: int | None = None) -> None:
        self.downloaded.append(material_id)

    def latest_transcode_payload(self, material_id: int) -> dict[str, Any] | None:
        return self.transcode_payload

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

    def default_voice_id(self) -> str:
        return "qwen-audio-3.0-tts-plus-test-voice"

    def create_voice_profile(self, *, name: str, voice_id: str) -> int:
        self.voice_profile = name, voice_id
        return 1

    def merge_job_payload(self, job_id: int, values: dict[str, Any]) -> None:
        self.job_payload_updates = job_id, values

    def update_material_title(self, material_id: int, title: str) -> None:
        self.updated_title = material_id, title

    def store_video_assets(self, **values: Any) -> None:
        self.video_assets = values

    def store_downloaded_video_assets(self, material_id: int, **values: Any) -> None:
        self.downloaded_video_assets.append((material_id, values))

    def replace_video_segments(self, material_id: int, segments: list[dict[str, Any]]) -> None:
        self.video_segments = segments

    def save_segment_translations(
        self, material_id: int, translations: list[str], *, offset: int = 0
    ) -> None:
        self.translation_batches.append((offset, len(translations)))
        stored = self.segment_translations or []
        needed = offset + len(translations)
        if len(stored) < needed:
            stored.extend([""] * (needed - len(stored)))
        for position, translation in enumerate(translations):
            stored[offset + position] = translation
        self.segment_translations = stored

    def translated_segment_indices(self, material_id: int) -> set[int]:
        return self.already_translated

    def mark_video_ready(self, material_id: int) -> None:
        self.video_ready.append(material_id)

    def get_segment(self, segment_id: int) -> dict[str, Any] | None:
        return {"id": segment_id, "text_ja": "雨です。"}

    def get_segments(self, material_id: int) -> list[dict[str, Any]]:
        return self.reading_segments

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


def test_failed_subtitle_translation_keeps_the_video_watchable() -> None:
    # A video is consumable once ASR has written Japanese subtitles. Losing the
    # Chinese line to a transient cloud timeout must not take away a material that
    # already cost a download, transcode, upload and ASR pass.
    job = Job(id=1, kind="translate_video", material_id=7, payload={"sentences": ["これは。"]}, attempts=1)
    repository = PipelineRepository([job])
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    worker.llm = StaticLLM(error="dashscope: The read operation timed out")  # type: ignore[assignment]

    assert worker.run_one() is True

    # Job records the diagnostic; material_id is None, so the material is untouched.
    assert repository.failed == [(1, None, "dashscope: The read operation timed out")]
    assert repository.segment_translations is None


def test_video_becomes_ready_after_subtitles_not_after_translation(tmp_path: Path) -> None:
    job = Job(
        id=1,
        kind="asr_video",
        material_id=7,
        payload={
            "audio_url": "https://oss.example.com/temporary/7.m4a",
            "temporary_audio_key": "temporary/7.m4a",
        },
        attempts=1,
    )
    repository = PipelineRepository([job])
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.storage = FakeStorage()  # type: ignore[assignment]
    worker.asr = StaticASR([RecognizedWord("これは。", 0, 1_200)])  # type: ignore[assignment]

    assert worker.run_one() is True

    assert repository.video_ready == [7]
    assert [job.kind for job in repository.enqueued] == ["translate_video"]


class BatchCountingLLM:
    """Fails on the Nth request, mimicking a read timeout part-way through."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.batch_sizes: list[int] = []
        self.fail_on_call = fail_on_call

    def reply(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        sentences = json.loads(messages[-1]["content"])
        self.batch_sizes.append(len(sentences))
        if self.fail_on_call is not None and self.calls == self.fail_on_call:
            raise RuntimeError("dashscope: The read operation timed out")
        return json.dumps([f"译{i}" for i in range(len(sentences))], ensure_ascii=False)


def test_long_transcript_is_translated_in_batches() -> None:
    # One request for a whole 137-line transcript hit the client's fixed read timeout
    # twice in practice; each request must stay small.
    sentences = [f"文{i}。" for i in range(137)]
    job = Job(id=1, kind="translate_video", material_id=7, payload={"sentences": sentences}, attempts=1)
    repository = PipelineRepository([job])
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    llm = BatchCountingLLM()
    worker.llm = llm  # type: ignore[assignment]

    assert worker.run_one() is True

    assert repository.failed == []
    assert max(llm.batch_sizes) <= 40
    assert sum(llm.batch_sizes) == 137
    assert repository.segment_translations is not None
    assert len(repository.segment_translations) == 137
    assert [offset for offset, _ in repository.translation_batches] == [0, 40, 80, 120]


def test_batch_failure_keeps_the_lines_already_translated() -> None:
    sentences = [f"文{i}。" for i in range(137)]
    job = Job(id=1, kind="translate_video", material_id=7, payload={"sentences": sentences}, attempts=1)
    repository = PipelineRepository([job])
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    worker.llm = BatchCountingLLM(fail_on_call=3)  # type: ignore[assignment]

    assert worker.run_one() is True

    assert repository.failed == [(1, None, "dashscope: The read operation timed out")]
    # Batches 1–2 survived; the material was never touched.
    assert repository.translation_batches == [(0, 40), (40, 40)]
    assert repository.video_ready == []


def test_retry_skips_batches_that_already_landed() -> None:
    # Batches are saved atomically, so a stored index means its whole batch succeeded.
    # Re-running after a late failure must not pay for those lines a second time.
    sentences = [f"文{i}。" for i in range(137)]
    job = Job(id=1, kind="translate_video", material_id=7, payload={"sentences": sentences}, attempts=2)
    repository = PipelineRepository([job])
    repository.already_translated = set(range(0, 80))  # first two batches survived
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    llm = BatchCountingLLM()
    worker.llm = llm  # type: ignore[assignment]

    assert worker.run_one() is True

    assert repository.failed == []
    # Only the two unfinished batches were sent.
    assert llm.batch_sizes == [40, 17]
    assert [offset for offset, _ in repository.translation_batches] == [80, 120]


def test_retry_with_nothing_stored_translates_everything() -> None:
    sentences = [f"文{i}。" for i in range(50)]
    job = Job(id=1, kind="translate_video", material_id=7, payload={"sentences": sentences}, attempts=2)
    repository = PipelineRepository([job])
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    llm = BatchCountingLLM()
    worker.llm = llm  # type: ignore[assignment]

    assert worker.run_one() is True

    assert llm.batch_sizes == [40, 10]


def test_failed_asr_only_fails_enhancement_job() -> None:
    repository = PipelineRepository([asr_job()])
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    worker.asr = StaticASR(error="ASR unavailable")  # type: ignore[assignment]

    assert worker.run_one() is True

    assert repository.processing == []
    assert repository.failed == [(1, None, "ASR unavailable")]


class FakeVideoProcessor:
    def create_hls(
        self,
        source: Path,
        video_directory: Path,
        audio_directory: Path,
        *,
        direct_video_copy: bool = False,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> str:
        for directory in (video_directory, audio_directory):
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "index.m3u8").write_text("#EXTM3U\nsegment-00000.ts\n")
            (directory / "segment-00000.ts").write_bytes(b"segment")
        return "copy" if direct_video_copy else "videotoolbox"

    def extract_audio(
        self, source: Path, destination: Path, *, start_ms: int | None = None, end_ms: int | None = None
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"audio")


class FakeStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str]] = []

    def validate_configuration(self) -> None:
        pass

    def upload_audio(self, local_path: Path, oss_key: str) -> str:
        self.uploads.append((local_path, oss_key))
        return self.public_url(oss_key)

    def upload_file(self, local_path: Path, oss_key: str) -> str:
        return self.upload_audio(local_path, oss_key)

    def upload_tree(self, directory: Path, oss_prefix: str) -> list[str]:
        keys = []
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            key = f"{oss_prefix}/{path.relative_to(directory).as_posix()}"
            self.uploads.append((path, key))
            keys.append(key)
        return keys

    def delete(self, oss_key: str) -> None:
        self.deleted_key = oss_key

    def public_url(self, oss_key: str) -> str:
        return f"https://media.example/{oss_key}"


class StaticLLM:
    def __init__(self, error: str | None = None) -> None:
        self.error = error

    def reply(self, messages: list[dict[str, str]]) -> str:
        if self.error:
            raise RuntimeError(self.error)
        sentences = json.loads(messages[-1]["content"])
        return json.dumps(["这是。" for _ in sentences], ensure_ascii=False)


class FakeTTS:
    def synthesize(self, *, text: str, destination: Path, voice: str | None = None) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"audio")


class FakeVideoDownloader:
    def __init__(self, source: Path) -> None:
        self.source = source

    def download(self, url: str, destination_directory: Path) -> Any:
        from app.video import DownloadedVideo

        return DownloadedVideo(path=self.source, title="下载到的标题")


class FakeVoiceEnrollment:
    def validate_configuration(self) -> None:
        pass

    def create_japanese_voice(self, *, audio_url: str, prefix: str) -> str:
        return f"qwen-audio-3.0-tts-plus-{prefix}-voice"


class FakeVideoVoiceExtractor:
    def extract(
        self,
        *,
        source: Path,
        work_directory: Path,
        start_seconds: float | None,
        duration_seconds: float,
    ) -> ExtractedVoiceSample:
        work_directory.mkdir(parents=True, exist_ok=True)
        sample = work_directory / "voice-sample.wav"
        sample.write_bytes(b"voice")
        return ExtractedVoiceSample(
            path=sample,
            mean_volume_db=-18.0,
            selected_start_seconds=42.0,
            selected_duration_seconds=20.0,
            quality_score=88.5,
            active_ratio=0.72,
            snr_db=18.0,
        )


class StaticVision:
    def extract_japanese(self, image_path: Path) -> str:
        return "雨です。"


def test_reading_pipeline_becomes_ready_before_optional_asr(
    monkeypatch: Any, tmp_path: Path
) -> None:
    initial = Job(id=1, kind="tts", material_id=7, payload={"text": "雨です。"}, attempts=1)
    repository = PipelineRepository([initial])
    repository.reading_segments = [{"idx": 0, "text_ja": "雨です。"}]
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.tts = FakeTTS()  # type: ignore[assignment]
    worker.storage = FakeStorage()  # type: ignore[assignment]
    worker.asr = StaticASR([RecognizedWord("雨です。", 0, 1_000)])  # type: ignore[assignment]
    worker.llm = StaticLLM()  # type: ignore[assignment]
    monkeypatch.setattr("app.worker.audio_duration_ms", lambda _: 1_000)

    while worker.run_one():
        pass

    assert [job.kind for job in repository.claimed] == ["tts", "asr", "translate_reading"]
    assert repository.processing == [7]
    assert repository.reading_completion is not None
    assert repository.tokens
    assert repository.segment_translations == ["这是。"]


def test_photo_pipeline_enters_reading_pipeline(monkeypatch: Any, tmp_path: Path) -> None:
    photo = tmp_path / "page.jpg"
    photo.write_bytes(b"photo")
    initial = Job(id=1, kind="vision", material_id=7, payload={"image_path": str(photo)}, attempts=1)
    repository = PipelineRepository([initial])
    repository.reading_segments = [{"idx": 0, "text_ja": "雨です。"}]
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.vision = StaticVision()  # type: ignore[assignment]
    worker.tts = FakeTTS()  # type: ignore[assignment]
    worker.storage = FakeStorage()  # type: ignore[assignment]
    worker.asr = StaticASR([RecognizedWord("雨です。", 0, 1_000)])  # type: ignore[assignment]
    worker.llm = StaticLLM()  # type: ignore[assignment]
    monkeypatch.setattr("app.worker.audio_duration_ms", lambda _: 1_000)

    while worker.run_one():
        pass

    assert [job.kind for job in repository.claimed] == ["vision", "tts", "asr", "translate_reading"]
    assert repository.processing == [7, 7]
    assert repository.reading_completion is not None
    assert repository.tokens


def test_video_pipeline_stops_after_local_transcode(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    initial = Job(id=1, kind="transcode", material_id=7, payload={"source_path": str(source)}, attempts=1)
    repository = PipelineRepository([initial])
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.video = FakeVideoProcessor()  # type: ignore[assignment]
    worker.storage = FakeStorage()  # type: ignore[assignment]

    while worker.run_one():
        pass

    # Download + transcode only; no OSS upload / ASR / translation until manual trigger.
    assert [job.kind for job in repository.claimed] == ["transcode"]
    assert repository.processing == [7]
    assert repository.downloaded == [7]
    assert repository.failed == []
    assert repository.video_assets is None
    assert worker.storage.uploads == []  # type: ignore[attr-defined]
    # §15.7's local-file purge can only find what's registered here — a material deleted
    # before its 转录 step would otherwise leave hls-video/hls-audio/asr-audio.m4a orphaned
    # on disk forever, because `store_video_assets` does not run until upload time.
    assert repository.downloaded_video_assets == [
        (
            7,
            {
                "video_directory": str(tmp_path / "video" / "material-7" / "hls-video"),
                "audio_directory": str(tmp_path / "video" / "material-7" / "hls-audio"),
                "asr_audio_path": str(tmp_path / "video" / "material-7" / "asr-audio.m4a"),
            },
        )
    ]


def test_video_link_download_stops_after_local_transcode(tmp_path: Path) -> None:
    source = tmp_path / "downloaded.mp4"
    source.write_bytes(b"source")
    initial = Job(
        id=1,
        kind="download_video",
        material_id=7,
        payload={"url": "https://example.com/video", "title_provided": False},
        attempts=1,
    )
    repository = PipelineRepository([initial])
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.video_downloader = FakeVideoDownloader(source)  # type: ignore[assignment]
    worker.video = FakeVideoProcessor()  # type: ignore[assignment]
    worker.storage = FakeStorage()  # type: ignore[assignment]

    while worker.run_one():
        pass

    assert [job.kind for job in repository.claimed] == ["download_video", "transcode"]
    assert repository.updated_title == (7, "下载到的标题")
    assert repository.downloaded == [7]
    assert worker.storage.uploads == []  # type: ignore[attr-defined]


def test_split_video_registers_local_assets_for_every_section(tmp_path: Path) -> None:
    # §15.7's local-file purge (`_purge_material_media`) can only delete what a material's
    # media_asset rows point it at. Before this registration existed, a section deleted
    # while still `downloaded` (untranscribed — §15.6's default resting state) left its
    # hls-video/hls-audio/asr-audio.m4a permanently orphaned on disk, because nothing wrote
    # local_path into media_asset until upload time.
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    job = Job(
        id=1,
        kind="split_video",
        material_id=None,
        payload={
            "source_path": str(source),
            "sections": [
                {"material_id": 40, "index": 1, "start_ms": 0, "end_ms": 10_000},
                {"material_id": 41, "index": 2, "start_ms": 10_000, "end_ms": None},
            ],
        },
        attempts=1,
    )
    repository = PipelineRepository([job])
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.video = FakeVideoProcessor()  # type: ignore[assignment]
    worker.storage = FakeStorage()  # type: ignore[assignment]

    while worker.run_one():
        pass

    assert repository.failed == []
    assert repository.downloaded == [40, 41]
    assert [material_id for material_id, _ in repository.downloaded_video_assets] == [40, 41]
    for material_id, values in repository.downloaded_video_assets:
        output_dir = tmp_path / "video" / f"material-{material_id}"
        assert values == {
            "video_directory": str(output_dir / "hls-video"),
            "audio_directory": str(output_dir / "hls-audio"),
            "asr_audio_path": str(output_dir / "asr-audio.m4a"),
        }


def test_requeued_split_skips_sections_already_cut(tmp_path: Path) -> None:
    """A requeued cut must not re-encode finished sections.

    Real case 2026-08-12: a 1h52m video's cut was interrupted, requeued, and started over
    from section 1 — about 12 minutes of ffmpeg per pass, with `worker_max_attempts = 3`.
    Two interruptions therefore burned every attempt redoing completed work and then failed
    the collection permanently.
    """

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    job = Job(
        id=1,
        kind="split_video",
        material_id=None,
        payload={
            "source_path": str(source),
            "sections": [
                {"material_id": 55, "index": 1, "start_ms": 0, "end_ms": 10_000},
                {"material_id": 56, "index": 2, "start_ms": 10_000, "end_ms": 20_000},
                {"material_id": 57, "index": 3, "start_ms": 20_000, "end_ms": None},
            ],
        },
        attempts=2,
    )
    repository = PipelineRepository([job])
    repository.already_cut = {55, 56}  # survived the interrupted first pass
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.video = FakeVideoProcessor()  # type: ignore[assignment]
    worker.storage = FakeStorage()  # type: ignore[assignment]

    while worker.run_one():
        pass

    assert repository.failed == []
    assert repository.downloaded == [57], "只有第 3 节需要重切"
    assert [material_id for material_id, _ in repository.downloaded_video_assets] == [57]
    assert not source.exists(), "全部小节齐了，原片仍然要按 §15.2 删掉"


def test_manual_transcription_chain_completes_pipeline(tmp_path: Path) -> None:
    # Simulates the manual "开始转录" trigger: an upload_video job is enqueued with
    # the locally-transcoded HLS paths, then the cloud chain runs to ready.
    video_dir = tmp_path / "hls-video"
    audio_dir = tmp_path / "hls-audio"
    for directory in (video_dir, audio_dir):
        directory.mkdir()
    (video_dir / "index.m3u8").write_text("#EXTM3U\n")
    (audio_dir / "index.m3u8").write_text("#EXTM3U\n")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    asr_audio = tmp_path / "asr-audio.m4a"
    asr_audio.write_bytes(b"audio")
    initial = Job(
        id=1,
        kind="upload_video",
        material_id=7,
        payload={
            "source_path": str(source),
            "video_directory": str(video_dir),
            "audio_directory": str(audio_dir),
            "asr_audio_path": str(asr_audio),
        },
        attempts=1,
    )
    repository = PipelineRepository([initial])
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.storage = FakeStorage()  # type: ignore[assignment]
    worker.asr = StaticASR([RecognizedWord("これは。", 0, 1_200)])  # type: ignore[assignment]
    worker.llm = StaticLLM()  # type: ignore[assignment]

    while worker.run_one():
        pass

    assert [job.kind for job in repository.claimed] == ["upload_video", "asr_video", "translate_video"]
    assert repository.failed == []
    assert repository.video_assets is not None
    assert repository.video_assets["video_playlist_key"].endswith("/hls/video/index.m3u8")
    assert repository.video_assets["audio_playlist_key"].endswith("/hls/audio/index.m3u8")
    # §15.7: without re-registering this at upload time, store_video_assets's own blanket
    # DELETE would remove the row store_downloaded_video_assets wrote pre-upload and leave
    # nothing behind — the local ASR audio file would go back to being un-findable.
    assert repository.video_assets["asr_audio_path"] == str(asr_audio)
    assert repository.video_segments == [
        {"idx": 0, "text_ja": "これは。", "start_ms": 0, "end_ms": 1_200}
    ]
    assert repository.tokens is not None
    assert [token["surface"] for token in repository.tokens] == ["これ", "は"]
    assert all(token["reading"] for token in repository.tokens)
    assert repository.segment_translations == ["这是。"]
    assert worker.storage.deleted_key == "temporary/materials/7/asr-audio.m4a"  # type: ignore[attr-defined]


def test_video_upload_failure_returns_material_to_downloaded_for_retry(tmp_path: Path) -> None:
    video_dir = tmp_path / "hls-video"
    audio_dir = tmp_path / "hls-audio"
    for directory in (video_dir, audio_dir):
        directory.mkdir()
        (directory / "index.m3u8").write_text("#EXTM3U\n")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    asr_audio = tmp_path / "asr-audio.m4a"
    asr_audio.write_bytes(b"audio")
    job = Job(
        id=1,
        kind="upload_video",
        material_id=7,
        payload={
            "source_path": str(source),
            "video_directory": str(video_dir),
            "audio_directory": str(audio_dir),
            "asr_audio_path": str(asr_audio),
        },
        attempts=1,
    )
    repository = PipelineRepository([job])
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]

    class FailingStorage(FakeStorage):
        def upload_tree(self, directory: Path, oss_prefix: str) -> list[str]:
            raise RuntimeError("OSS timeout")

    worker.storage = FailingStorage()  # type: ignore[assignment]

    assert worker.run_one() is True

    assert repository.failed == [(1, None, "OSS timeout")]
    assert repository.downloaded == [7]


def test_voice_enrollment_uses_temporary_oss_and_creates_default_profile(tmp_path: Path) -> None:
    sample = tmp_path / "sample.m4a"
    sample.write_bytes(b"voice")
    job = Job(
        id=1,
        kind="voice_enrollment",
        material_id=None,
        payload={"name": "我的声音", "prefix": "mine", "sample_path": str(sample)},
        attempts=1,
    )
    repository = PipelineRepository([job])
    worker = Worker(repository, Settings())  # type: ignore[arg-type]
    worker.storage = FakeStorage()  # type: ignore[assignment]
    worker.voice_enrollment = FakeVoiceEnrollment()  # type: ignore[assignment]

    with patch("app.worker.audio_duration_ms", return_value=10_000):
        assert worker.run_one() is True

    assert repository.voice_profile == ("我的声音", "qwen-audio-3.0-tts-plus-mine-voice")
    assert worker.storage.deleted_key.startswith("temporary/voice-profiles/")  # type: ignore[attr-defined]


def test_video_voice_enrollment_selects_sample_and_creates_default_profile(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    job = Job(
        id=1,
        kind="voice_enrollment_video",
        material_id=None,
        payload={
            "name": "视频声音",
            "prefix": "movie",
            "source_path": str(source),
            "selection_mode": "auto",
            "clip_start_seconds": None,
            "clip_duration_seconds": 20,
        },
        attempts=1,
    )
    repository = PipelineRepository([job])
    worker = Worker(repository, Settings(data_dir=tmp_path))  # type: ignore[arg-type]
    worker.storage = FakeStorage()  # type: ignore[assignment]
    worker.voice_enrollment = FakeVoiceEnrollment()  # type: ignore[assignment]
    worker.video_voice_extractor = FakeVideoVoiceExtractor()  # type: ignore[assignment]

    with patch("app.worker.audio_duration_ms", return_value=20_000):
        assert worker.run_one() is True

    assert repository.failed == []
    assert repository.done == [1]
    assert repository.voice_profile == ("视频声音", "qwen-audio-3.0-tts-plus-movie-voice")
    assert repository.job_payload_updates is not None
    assert repository.job_payload_updates[1]["selected_start_seconds"] == 42.0
    assert repository.job_payload_updates[1]["quality_score"] == 88.5
    assert not source.exists()


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
