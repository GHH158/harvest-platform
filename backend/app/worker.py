from __future__ import annotations

import argparse
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from mutagen import File as MutagenFile

from .config import Settings, get_settings
from .db import make_engine
from .repository import Job, Repository
from .storage import ObjectStorage
from .text import estimated_segments
from .tts import TTSService


class Worker:
    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.tts = TTSService(settings)
        self.storage = ObjectStorage(settings)

    def run_one(self) -> bool:
        job = self.repository.claim_next_job()
        if job is None:
            return False
        try:
            if job.material_id is None:
                raise RuntimeError("P1 worker job 缺少 material_id。")
            self.repository.mark_material_processing(job.material_id)
            if job.kind == "fetch":
                self._fetch(job)
            elif job.kind == "tts":
                self._synthesize(job)
            else:
                raise RuntimeError(f"P1 不支持的任务类型: {job.kind}")
        except Exception as error:  # The error must be persisted for the ingest UI and diagnostics.
            self.repository.mark_job_failed(job.id, job.material_id, str(error))
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
        self.repository.enqueue_job(
            kind="tts",
            material_id=job.material_id or 0,
            payload={"text": article_text, "title_from_page": title},
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


def extract_article(url: str) -> tuple[str | None, str]:
    with httpx.Client(
        timeout=30.0, follow_redirects=True, headers={"User-Agent": "Harvest/0.1"}
    ) as client:
        response = client.get(url)
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for ignored in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        ignored.decompose()
    root = soup.find("article") or soup.find("main") or soup.body
    if root is None:
        return soup.title.get_text(" ", strip=True) if soup.title else None, ""
    text = "\n".join(part.strip() for part in root.stripped_strings)
    title = soup.title.get_text(" ", strip=True) if soup.title else urlparse(url).netloc
    return title, text


def audio_duration_ms(path: Path) -> int:
    audio = MutagenFile(path)
    if audio is None or audio.info.length <= 0:
        raise RuntimeError("无法读取 TTS 音频时长。")
    return max(1, round(audio.info.length * 1000))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Harvest P1 job worker.")
    parser.add_argument(
        "--once", action="store_true", help="Process at most one pending job, then exit."
    )
    args = parser.parse_args()
    settings = get_settings()
    worker = Worker(Repository(make_engine(settings)), settings)
    if args.once:
        worker.run_one()
        return
    print("Harvest worker is polling the job table.", flush=True)
    while True:
        if not worker.run_one():
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
