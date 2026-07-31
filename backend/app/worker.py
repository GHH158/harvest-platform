from __future__ import annotations

import argparse
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from mutagen import File as MutagenFile
from trafilatura.metadata import extract_metadata

from .alignment import align_words_to_source
from .asr import ASRService
from .config import Settings, get_settings
from .db import make_engine
from .repository import Job, Repository
from .shadowing import score_transcript
from .storage import ObjectStorage
from .text import estimated_segments
from .tts import TTSService
from .video import VideoProcessor
from .vision import VisionService


class Worker:
    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.tts = TTSService(settings)
        self.asr = ASRService(settings)
        self.storage = ObjectStorage(settings)
        self.video = VideoProcessor()
        self.vision = VisionService(settings)

    def run_one(self) -> bool:
        exhausted = self.repository.fail_exhausted_pending_jobs(max_attempts=self.settings.worker_max_attempts)
        if exhausted:
            print(f"marked {exhausted} exhausted job(s) as failed", flush=True)
        job = self.repository.claim_next_job(max_attempts=self.settings.worker_max_attempts)
        if job is None:
            return False
        try:
            if job.material_id is None and job.kind != "shadowing":
                raise RuntimeError("P1 worker job 缺少 material_id。")
            if job.material_id is not None:
                self.repository.mark_material_processing(job.material_id)
            if job.kind == "fetch":
                self._fetch(job)
            elif job.kind == "tts":
                self._synthesize(job)
            elif job.kind == "asr":
                self._align_asr(job)
            elif job.kind == "shadowing":
                self._score_shadowing(job)
            elif job.kind == "transcode":
                self._transcode_video(job)
            elif job.kind == "vision":
                self._extract_photo(job)
            else:
                raise RuntimeError(f"P1 不支持的任务类型: {job.kind}")
        except Exception as error:  # The error must be persisted for the ingest UI and diagnostics.
            # P2 ASR improves P1's estimated sentence timing. If recognition
            # fails, retain the already playable sentence-level material and
            # only record the diagnostic on its own job.
            self.repository.mark_job_failed(job.id, None if job.kind == "asr" else job.material_id, str(error))
            print(f"job={job.id} failed: {error}", flush=True)
        else:
            self.repository.mark_job_done(job.id)
            print(f"job={job.id} done", flush=True)
        return True

    def _fetch(self, job: Job) -> None:
        url = str(job.payload.get("url", ""))
        if not url:
            raise RuntimeError("fetch 任务缺少 URL。")
        title, article_text = extract_article(url)
        if not article_text:
            raise RuntimeError("未能从网页提取可朗读的正文。")
        if title and not bool(job.payload.get("title_provided")):
            self.repository.update_material_title(job.material_id or 0, title)
        self.repository.enqueue_job(
            kind="tts",
            material_id=job.material_id or 0,
            payload={"text": article_text},
        )

    def _synthesize(self, job: Job) -> None:
        source_text = str(job.payload.get("text", "")).strip()
        if not source_text:
            raise RuntimeError("tts 任务缺少文本。")
        assert job.material_id is not None
        audio_path = self.settings.local_audio_dir / f"material-{job.material_id}.mp3"
        self.tts.synthesize(text=source_text, destination=audio_path)
        duration_ms = audio_duration_ms(audio_path)
        oss_key = f"materials/{job.material_id}/reading.mp3"
        self.storage.upload_audio(audio_path, oss_key)
        self.repository.complete_reading(
            material_id=job.material_id,
            local_path=str(audio_path),
            oss_key=oss_key,
            bytes_count=audio_path.stat().st_size,
            duration_ms=duration_ms,
            segments=estimated_segments(source_text, duration_ms),
        )
        self.repository.enqueue_job(
            kind="asr",
            material_id=job.material_id,
            payload={"text": source_text, "audio_url": self.storage.public_url(oss_key)},
        )

    def _align_asr(self, job: Job) -> None:
        source_text = str(job.payload.get("text", "")).strip()
        audio_url = str(job.payload.get("audio_url", "")).strip()
        if not source_text or not audio_url:
            raise RuntimeError("asr 任务缺少原文或音频 URL。")
        assert job.material_id is not None
        alignment = align_words_to_source(source_text, self.asr.transcribe_words(audio_url))
        if alignment.coverage < 0.6:
            print(
                f"job={job.id} ASR 对齐覆盖率 {alignment.coverage:.0%}，保留 P1 句级估算时间轴。",
                flush=True,
            )
            return
        self.repository.replace_tokens(
            job.material_id,
            [
                {
                    "segment_idx": token.segment_idx,
                    "idx": token.idx,
                    "surface": token.surface,
                    "start_ms": token.start_ms,
                    "end_ms": token.end_ms,
                }
                for token in alignment.tokens
            ],
        )

    def _score_shadowing(self, job: Job) -> None:
        attempt_id = int(job.payload.get("attempt_id", 0))
        segment_id = int(job.payload.get("segment_id", 0))
        audio_path = Path(str(job.payload.get("audio_path", "")))
        segment = self.repository.get_segment(segment_id)
        if not attempt_id or segment is None or not audio_path.exists():
            raise RuntimeError("shadowing 任务缺少录音或原句。")
        oss_key = f"shadowing/{attempt_id}/{audio_path.name}"
        self.storage.upload_audio(audio_path, oss_key)
        words = self.asr.transcribe_words(self.storage.public_url(oss_key))
        transcript = "".join(word.text for word in words)
        score, diff = score_transcript(str(segment["text_ja"]), transcript)
        self.repository.complete_shadowing_attempt(attempt_id, transcript, diff, score)

    def _transcode_video(self, job: Job) -> None:
        source = Path(str(job.payload.get("source_path", "")))
        if not source.exists() or job.material_id is None:
            raise RuntimeError("transcode 任务缺少本地视频文件。")
        output_dir = self.settings.data_dir / "video" / f"material-{job.material_id}"
        delivery = output_dir / "delivery-720p.mp4"
        audio = output_dir / "audio.m4a"
        self.video.transcode_delivery(source, delivery)
        self.video.extract_audio(source, audio)
        self.repository.enqueue_job(
            kind="upload_video",
            material_id=job.material_id,
            payload={"delivery_path": str(delivery), "audio_path": str(audio)},
        )

    def _extract_photo(self, job: Job) -> None:
        image_path = Path(str(job.payload.get("image_path", "")))
        if job.material_id is None or not image_path.exists():
            raise RuntimeError("vision 任务缺少照片文件。")
        text = self.vision.extract_japanese(image_path)
        self.repository.enqueue_job(kind="tts", material_id=job.material_id, payload={"text": text})


def extract_article(url: str) -> tuple[str | None, str]:
    with httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": "Harvest/0.1"}) as client:
        response = client.get(url)
        response.raise_for_status()
    return extract_article_html(response.text, url)


def extract_article_html(html: str, source_url: str) -> tuple[str | None, str]:
    """Use a readability-class extractor, with a conservative HTML fallback."""
    metadata = extract_metadata(html)
    title = metadata.title if metadata and metadata.title else urlparse(source_url).netloc
    soup = BeautifulSoup(html, "html.parser")
    for ignored in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        ignored.decompose()
    extracted = trafilatura.extract(str(soup), include_comments=False, include_tables=False)
    if extracted:
        return title, extracted.strip()

    root = soup.find("article") or soup.find("main") or soup.body
    if root is None:
        return title, ""
    text = "\n".join(part.strip() for part in root.stripped_strings)
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    return title, text


def audio_duration_ms(path: Path) -> int:
    audio = MutagenFile(path)
    if audio is None or audio.info.length <= 0:
        raise RuntimeError("无法读取 TTS 音频时长。")
    return max(1, round(audio.info.length * 1000))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Harvest P1 job worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one pending job, then exit.")
    args = parser.parse_args()
    settings = get_settings()
    repository = Repository(make_engine(settings))
    recovered = repository.recover_stale_running_jobs(stale_seconds=settings.worker_stale_running_seconds)
    if recovered:
        print(f"requeued {recovered} interrupted job(s)", flush=True)
    worker = Worker(repository, settings)
    if args.once:
        worker.run_one()
        return
    print("Harvest worker is polling the job table.", flush=True)
    while True:
        if not worker.run_one():
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
