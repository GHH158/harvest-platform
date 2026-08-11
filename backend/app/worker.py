from __future__ import annotations

import argparse
import json
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from mutagen import File as MutagenFile
from trafilatura.metadata import extract_metadata

from .alignment import align_words_to_source
from .asr import ASRService, RecognizedWord
from .config import Settings, get_settings
from .db import make_engine
from .llm import LLMService
from .prompts import SUBTITLE_TRANSLATION_SYSTEM_PROMPT
from .repository import Job, Repository
from .shadowing import score_transcript
from .storage import ObjectStorage
from .text import estimated_segments
from .tts import TTSService
from .video import HLSBundleError, VideoDownloader, VideoProcessor, is_hls_playlist, unpack_hls_bundle
from .vision import VisionService
from .voice import VideoVoiceExtractor, VoiceEnrollmentService, validate_voice_sample_duration

ENHANCEMENT_JOB_KINDS = {"asr", "translate_reading", "translate_video"}

# Sentences per subtitle-translation request. Sized against the LLM client's fixed
# read timeout: 46 sentences in one call succeeded, 137 timed out twice.
TRANSLATION_BATCH_SIZE = 40
# Jobs that legitimately belong to no single material. `split_video` is one because it
# produces many of them at once (§15.2) — attaching it to any one section would make that
# section's status and error message stand in for the whole cut.
STANDALONE_JOB_KINDS = {
    "shadowing",
    "voice_enrollment",
    "voice_enrollment_video",
    "split_video",
    # §15.11: relayed through OSS rather than the request body, so no material exists
    # yet — same reason `split_video` is on this list.
    "fetch_video_upload",
}


class Worker:
    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.tts = TTSService(settings)
        self.asr = ASRService(settings)
        self.storage = ObjectStorage(settings)
        self.video = VideoProcessor(
            max_threads=settings.video_transcode_max_threads,
            max_height=settings.video_download_max_height,
        )
        self.video_downloader = VideoDownloader(
            max_bytes=settings.max_video_upload_bytes,
            min_free_bytes=settings.min_free_disk_bytes,
            max_height=settings.video_download_max_height,
            max_fps=settings.video_download_max_fps,
        )
        self.vision = VisionService(settings)
        self.llm = LLMService(settings)
        self.voice_enrollment = VoiceEnrollmentService(settings)
        self.video_voice_extractor = VideoVoiceExtractor(settings.data_dir)

    def run_one(self) -> bool:
        exhausted = self.repository.fail_exhausted_pending_jobs(max_attempts=self.settings.worker_max_attempts)
        if exhausted:
            print(f"marked {exhausted} exhausted job(s) as failed", flush=True)
        job = self.repository.claim_next_job(max_attempts=self.settings.worker_max_attempts)
        if job is None:
            return False
        try:
            if job.material_id is None and job.kind not in STANDALONE_JOB_KINDS:
                raise RuntimeError("P1 worker job 缺少 material_id。")
            if job.material_id is not None and job.kind not in ENHANCEMENT_JOB_KINDS:
                self.repository.mark_material_processing(job.material_id)
            if job.kind == "fetch":
                self._fetch(job)
            elif job.kind == "tts":
                self._synthesize(job)
            elif job.kind == "asr":
                self._align_asr(job)
            elif job.kind == "translate_reading":
                self._translate_reading(job)
            elif job.kind == "shadowing":
                self._score_shadowing(job)
            elif job.kind == "split_video":
                self._split_video(job)
            elif job.kind == "transcode":
                self._transcode_video(job)
            elif job.kind == "download_video":
                self._download_video(job)
            elif job.kind == "vision":
                self._extract_photo(job)
            elif job.kind == "upload_video":
                self._upload_video(job)
            elif job.kind == "asr_video":
                self._transcribe_video(job)
            elif job.kind == "translate_video":
                self._translate_video(job)
            elif job.kind == "voice_enrollment":
                self._enroll_voice(job)
            elif job.kind == "voice_enrollment_video":
                self._enroll_voice_from_video(job)
            elif job.kind == "fetch_video_upload":
                self._fetch_video_upload(job)
            else:
                raise RuntimeError(f"不支持的任务类型: {job.kind}")
        except Exception as error:  # The error must be persisted for the ingest UI and diagnostics.
            # Enhancement jobs (ASR word timing, reading translation) improve an
            # already-playable material. If they fail, keep the material ready
            # and only record the diagnostic on its own job.
            retryable_video_upload = job.kind == "upload_video" and job.material_id is not None
            failure_material_id = None if job.kind in ENHANCEMENT_JOB_KINDS or retryable_video_upload else job.material_id
            self.repository.mark_job_failed(job.id, failure_material_id, str(error))
            if retryable_video_upload:
                self.repository.mark_material_downloaded(job.material_id)
            if job.kind == "shadowing":
                self.repository.fail_shadowing_attempt(int(job.payload.get("attempt_id", 0)), str(error))
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
        self.tts.synthesize(
            text=source_text,
            destination=audio_path,
            voice=self.settings.dashscope_tts_voice or self.repository.default_voice_id(),
        )
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
        self.repository.enqueue_job(kind="translate_reading", material_id=job.material_id, payload={})

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
                    "reading": token.reading,
                    "start_ms": token.start_ms,
                    "end_ms": token.end_ms,
                }
                for token in alignment.tokens
            ],
        )

    def _translate_sentences(self, material_id: int, sentences: list[str], *, label: str) -> None:
        """Translate a whole transcript in batches, persisting each batch as it lands.

        One request for the entire transcript hits the LLM client's fixed read timeout
        once a material gets long — measured: 22 and 46 sentences succeeded, 137 timed
        out twice. Batching keeps each request short, and saving per batch means a late
        failure leaves the earlier lines translated instead of losing everything.

        A retry resumes: batches already stored are skipped rather than paid for twice.
        """
        already_translated = self.repository.translated_segment_indices(material_id)
        for start in range(0, len(sentences), TRANSLATION_BATCH_SIZE):
            batch = sentences[start : start + TRANSLATION_BATCH_SIZE]
            batch_indices = range(start, start + len(batch))
            if all(index in already_translated for index in batch_indices):
                print(f"material={material_id} 跳过已翻译的第 {start}–{start + len(batch) - 1} 句。", flush=True)
                continue
            answer = self.llm.reply(
                [
                    {"role": "system", "content": SUBTITLE_TRANSLATION_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
                ]
            )
            translations = json.loads(answer)
            if not isinstance(translations, list) or len(translations) != len(batch):
                raise RuntimeError(f"{label}翻译返回数量不匹配。")
            self.repository.save_segment_translations(
                material_id, [str(item) for item in translations], offset=start
            )

    def _translate_reading(self, job: Job) -> None:
        assert job.material_id is not None
        segments = self.repository.get_segments(job.material_id)
        sentences = [str(segment["text_ja"]) for segment in segments]
        if not sentences:
            raise RuntimeError("阅读材料缺少分句，无法翻译。")
        self._translate_sentences(job.material_id, sentences, label="阅读材料")

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
        video_directory = output_dir / "hls-video"
        audio_directory = output_dir / "hls-audio"
        asr_audio = output_dir / "asr-audio.m4a"
        thumbnail = output_dir / "thumbnail.jpg"
        try:
            self.video.create_thumbnail(source, thumbnail)
            self.repository.store_material_thumbnail(job.material_id, str(thumbnail))
        except Exception as error:
            print(f"job={job.id} 无法生成视频缩略图: {error}", flush=True)
        video_mode = self.video.create_hls(
            source,
            video_directory,
            audio_directory,
            direct_video_copy=bool(job.payload.get("direct_hls_compatible")),
        )
        self.video.extract_audio(source, asr_audio)
        self.repository.merge_job_payload(job.id, {"video_mode": video_mode})
        # Stop here: the video is downloaded and transcoded locally but NOT uploaded.
        # Uploading to OSS (and the ASR/translate that follow) generates cloud traffic,
        # so it must be triggered manually from the materials page. The transcode job's
        # payload keeps source_path so the trigger can rebuild the upload payload.
        try:
            duration_ms = audio_duration_ms(asr_audio)
        except Exception:
            duration_ms = None
        self.repository.mark_material_downloaded(job.material_id, duration_ms=duration_ms)

    def _fetch_video_upload(self, job: Job) -> None:
        """Pull a raw upload down from OSS and land it exactly where §15.2 expects one to
        already be (§15.11).

        This exists because the phone's own uplink to the Mac over Tailscale is
        sometimes the bottleneck — §3.3 measured this for HLS *playback*, and the same
        weak link cuts the other direction for a raw upload. When the phone measures that
        and picks OSS instead of `POST /videos/uploads`, this job is the other half: OSS
        has already taken the bytes, so what is slow now is only the Mac's own downlink,
        which is usually the strong side of a home connection rather than the weak one.

        The result is written into the same `pending-<uuid>` shape that
        `POST /videos/uploads` produces inline, so `POST /collections` cannot tell which
        path a given upload took.
        """

        oss_key = str(job.payload.get("oss_key", ""))
        filename = str(job.payload.get("filename", ""))
        if not oss_key.startswith("temporary/raw-uploads/") or not filename:
            raise RuntimeError("fetch_video_upload 任务缺少来源信息。")
        self.storage.validate_configuration()
        # Checked before spending any bandwidth or disk on the download: a direct upload
        # is checked against this same limit while it streams in, but going through OSS
        # skips that check entirely until this line runs.
        size = self.storage.object_size(oss_key)
        if size > self.settings.max_video_upload_bytes:
            self.storage.delete(oss_key)
            raise RuntimeError("视频太大，超出了单次上传的限制。")
        suffix = Path(filename).suffix.lower() or ".mp4"
        video_dir = self.settings.data_dir / "video" / "uploads"
        video_dir.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(video_dir).free < self.settings.min_free_disk_bytes:
            raise RuntimeError("本机磁盘空间不足，暂不能接收视频。")
        destination = video_dir / f"pending-{uuid.uuid4().hex}{suffix}"
        self.storage.download_to_file(oss_key, destination)
        try:
            self.storage.delete(oss_key)
        except Exception as error:
            print(f"job={job.id} 无法删除临时上传对象: {error}", flush=True)
        if suffix == ".zip":
            try:
                playlist = unpack_hls_bundle(destination)
            except HLSBundleError as error:
                destination.unlink(missing_ok=True)
                raise RuntimeError(str(error)) from error
            destination.unlink(missing_ok=True)
            upload_id = str(playlist.relative_to(video_dir))
        else:
            upload_id = destination.name
        self.repository.merge_job_payload(job.id, {"upload_id": upload_id, "filename": filename})

    def _split_video(self, job: Job) -> None:
        """Cut one uploaded video into the sections the learner marked on their phone (§15).

        Each section is produced exactly the way a whole video would be — 720p video HLS,
        audio-only HLS, thumbnail, ASR track — and stops at `downloaded`, so nothing reaches
        OSS until a section's 转录 is tapped (§5.2 step ④, §15.6).

        Sections are processed one at a time and each is marked as it finishes, so a
        collection is usable while the rest are still encoding, and a failure halfway
        leaves the finished sections intact rather than losing the whole upload.
        """

        source = Path(str(job.payload.get("source_path", "")))
        sections = list(job.payload.get("sections") or [])
        if not source.exists() or not sections:
            raise RuntimeError("split_video 任务缺少源文件或拆分区间。")
        failures: list[str] = []
        for section in sections:
            material_id = int(section["material_id"])
            start_ms = int(section["start_ms"])
            end_ms = section.get("end_ms")
            end_ms = int(end_ms) if end_ms is not None else None
            output_dir = self.settings.data_dir / "video" / f"material-{material_id}"
            video_directory = output_dir / "hls-video"
            audio_directory = output_dir / "hls-audio"
            asr_audio = output_dir / "asr-audio.m4a"
            thumbnail = output_dir / "thumbnail.jpg"
            try:
                try:
                    self.video.create_thumbnail(source, thumbnail, at_ms=start_ms)
                    self.repository.store_material_thumbnail(material_id, str(thumbnail))
                except Exception as error:
                    print(f"job={job.id} 第 {material_id} 节缩略图失败: {error}", flush=True)
                self.video.create_hls(
                    source,
                    video_directory,
                    audio_directory,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
                self.video.extract_audio(source, asr_audio, start_ms=start_ms, end_ms=end_ms)
                try:
                    duration_ms = audio_duration_ms(asr_audio)
                except Exception:
                    duration_ms = None if end_ms is None else end_ms - start_ms
                self.repository.mark_material_downloaded(material_id, duration_ms=duration_ms)
            except Exception as error:
                # One bad section must not cost the others. It stays failed and retryable
                # while its siblings become usable.
                failures.append(f"第 {section.get('index', material_id)} 节: {error}")
                self.repository.mark_material_failed(material_id, str(error))
        # §15.2 / §15.7: the source's only purpose was this cut, so it goes — but not while
        # a section still needs re-cutting from it.
        #
        # For an HLS bundle the source is a playlist inside an extracted directory, and
        # deleting just the playlist would leave hundreds of segments behind forever.
        if not failures:
            if is_hls_playlist(source):
                shutil.rmtree(source.parent, ignore_errors=True)
            else:
                source.unlink(missing_ok=True)
        if failures:
            raise RuntimeError("；".join(failures))

    def _download_video(self, job: Job) -> None:
        url = str(job.payload.get("url", "")).strip()
        if not url or job.material_id is None:
            raise RuntimeError("download_video 任务缺少视频链接。")
        destination = self.settings.data_dir / "video" / "downloads" / f"material-{job.material_id}"
        downloaded = self.video_downloader.download(url, destination)
        if not bool(job.payload.get("title_provided")):
            self.repository.update_material_title(job.material_id, downloaded.title)
        self.repository.enqueue_job(
            kind="transcode",
            material_id=job.material_id,
            payload={
                "source_path": str(downloaded.path),
                "source_height": downloaded.height,
                "source_fps": downloaded.fps,
                "source_vcodec": downloaded.vcodec,
                "direct_hls_compatible": downloaded.direct_hls_compatible,
            },
        )

    def _extract_photo(self, job: Job) -> None:
        image_path = Path(str(job.payload.get("image_path", "")))
        if job.material_id is None or not image_path.exists():
            raise RuntimeError("vision 任务缺少照片文件。")
        text = self.vision.extract_japanese(image_path)
        self.repository.enqueue_job(kind="tts", material_id=job.material_id, payload={"text": text})

    def _upload_video(self, job: Job) -> None:
        assert job.material_id is not None
        video_directory = Path(str(job.payload.get("video_directory", "")))
        audio_directory = Path(str(job.payload.get("audio_directory", "")))
        video_playlist = video_directory / "index.m3u8"
        audio_playlist = audio_directory / "index.m3u8"
        asr_audio = Path(str(job.payload.get("asr_audio_path", "")))
        source = Path(str(job.payload.get("source_path", "")))
        if not source.exists() or not video_playlist.exists() or not audio_playlist.exists() or not asr_audio.exists():
            raise RuntimeError("upload_video 任务缺少 HLS 或 ASR 音轨。")
        video_prefix = f"materials/{job.material_id}/hls/video"
        audio_prefix = f"materials/{job.material_id}/hls/audio"
        video_playlist_key = f"{video_prefix}/index.m3u8"
        audio_playlist_key = f"{audio_prefix}/index.m3u8"
        temporary_audio_key = f"temporary/materials/{job.material_id}/asr-audio.m4a"
        self.storage.upload_tree(video_directory, video_prefix)
        self.storage.upload_tree(audio_directory, audio_prefix)
        self.storage.upload_file(asr_audio, temporary_audio_key)
        self.repository.store_video_assets(
            material_id=job.material_id,
            source_path=str(source),
            video_playlist_path=str(video_playlist),
            audio_playlist_path=str(audio_playlist),
            video_playlist_key=video_playlist_key,
            audio_playlist_key=audio_playlist_key,
        )
        self.repository.enqueue_job(
            kind="asr_video",
            material_id=job.material_id,
            payload={
                "audio_url": self.storage.public_url(temporary_audio_key),
                "temporary_audio_key": temporary_audio_key,
            },
        )

    def _transcribe_video(self, job: Job) -> None:
        assert job.material_id is not None
        audio_url = str(job.payload.get("audio_url", ""))
        if not audio_url:
            raise RuntimeError("asr_video 任务缺少音频 URL。")
        words = self.asr.transcribe_words(audio_url)
        segments: list[dict[str, int | str]] = []
        current: list[RecognizedWord] = []
        for word in words:
            current.append(word)
            if any(mark in word.text for mark in "。！？!?"):
                segments.append(
                    {
                        "idx": len(segments),
                        "text_ja": "".join(item.text for item in current),
                        "start_ms": current[0].start_ms,
                        "end_ms": current[-1].end_ms,
                    }
                )
                current = []
        if current:
            segments.append(
                {
                    "idx": len(segments),
                    "text_ja": "".join(item.text for item in current),
                    "start_ms": current[0].start_ms,
                    "end_ms": current[-1].end_ms,
                }
            )
        if not segments:
            raise RuntimeError("视频 ASR 未返回字幕。")
        self.repository.replace_video_segments(job.material_id, segments)
        alignment = align_words_to_source("".join(str(item["text_ja"]) for item in segments), words)
        self.repository.replace_tokens(
            job.material_id,
            [
                {
                    "segment_idx": token.segment_idx,
                    "idx": token.idx,
                    "surface": token.surface,
                    "reading": token.reading,
                    "start_ms": token.start_ms,
                    "end_ms": token.end_ms,
                }
                for token in alignment.tokens
            ],
        )
        # The video is watchable from here on: subtitles, word timing and 点词陪读 all
        # work. Chinese translation is an enhancement queued below, and a transient
        # failure there must not take the whole material away.
        self.repository.mark_video_ready(job.material_id)
        self.repository.enqueue_job(
            kind="translate_video",
            material_id=job.material_id,
            payload={
                "sentences": [item["text_ja"] for item in segments],
                "temporary_audio_key": str(job.payload.get("temporary_audio_key", "")),
            },
        )

    def _translate_video(self, job: Job) -> None:
        assert job.material_id is not None
        sentences = [str(item) for item in job.payload.get("sentences", [])]
        if not sentences:
            raise RuntimeError("translate_video 任务缺少字幕。")
        self._translate_sentences(job.material_id, sentences, label="字幕")
        temporary_audio_key = str(job.payload.get("temporary_audio_key", ""))
        if temporary_audio_key:
            try:
                self.storage.delete(temporary_audio_key)
            except Exception as error:
                print(f"job={job.id} 无法删除 ASR 临时音轨: {error}", flush=True)

    def _enroll_voice(self, job: Job) -> None:
        sample_path = Path(str(job.payload.get("sample_path", "")))
        name = str(job.payload.get("name", "")).strip()
        prefix = str(job.payload.get("prefix", "")).strip()
        if not sample_path.exists() or not name or not prefix:
            raise RuntimeError("voice_enrollment 任务缺少音色名称、前缀或参考录音。")
        self.voice_enrollment.validate_configuration()
        self.storage.validate_configuration()
        validate_voice_sample_duration(audio_duration_ms(sample_path))
        oss_key = f"temporary/voice-profiles/{job.id}/{sample_path.name}"
        self.storage.upload_audio(sample_path, oss_key)
        voice_id = self.voice_enrollment.create_japanese_voice(
            audio_url=self.storage.public_url(oss_key),
            prefix=prefix,
        )
        self.repository.create_voice_profile(name=name, voice_id=voice_id)
        sample_path.unlink(missing_ok=True)
        try:
            self.storage.delete(oss_key)
        except Exception as error:
            print(f"job={job.id} 无法删除音色参考录音: {error}", flush=True)

    def _enroll_voice_from_video(self, job: Job) -> None:
        source_path = Path(str(job.payload.get("source_path", "")))
        name = str(job.payload.get("name", "")).strip()
        prefix = str(job.payload.get("prefix", "")).strip()
        selection_mode = str(job.payload.get("selection_mode", "auto")).strip().lower()
        if not source_path.exists() or not name or not prefix:
            raise RuntimeError("voice_enrollment_video 任务缺少音色名称、前缀或原始视频。")
        if selection_mode not in {"auto", "manual"}:
            raise RuntimeError("voice_enrollment_video 任务的片段选择方式无效。")
        self.voice_enrollment.validate_configuration()
        self.storage.validate_configuration()
        raw_start = job.payload.get("clip_start_seconds")
        if selection_mode == "manual" and raw_start is None:
            raise RuntimeError("voice_enrollment_video 手动模式缺少片段起点。")
        start_seconds = None if selection_mode == "auto" else float(raw_start)
        duration_seconds = float(job.payload.get("clip_duration_seconds", 20.0))
        work_directory = self.settings.data_dir / "voice-profiles" / "processed" / f"job-{job.id}"
        sample = self.video_voice_extractor.extract(
            source=source_path,
            work_directory=work_directory,
            start_seconds=start_seconds,
            duration_seconds=duration_seconds,
        )
        self.repository.merge_job_payload(
            job.id,
            {
                "selected_start_seconds": sample.selected_start_seconds,
                "selected_duration_seconds": sample.selected_duration_seconds,
                "mean_volume_db": sample.mean_volume_db,
                "quality_score": sample.quality_score,
                "active_ratio": sample.active_ratio,
                "snr_db": sample.snr_db,
            },
        )
        validate_voice_sample_duration(audio_duration_ms(sample.path))
        oss_key = f"temporary/voice-profiles/{job.id}/{sample.path.name}"
        self.storage.upload_audio(sample.path, oss_key)
        voice_id = self.voice_enrollment.create_japanese_voice(
            audio_url=self.storage.public_url(oss_key),
            prefix=prefix,
        )
        self.repository.create_voice_profile(name=name, voice_id=voice_id)
        source_path.unlink(missing_ok=True)
        shutil.rmtree(work_directory, ignore_errors=True)
        try:
            self.storage.delete(oss_key)
        except Exception as error:
            print(f"job={job.id} 无法删除视频音色参考录音: {error}", flush=True)


def extract_article(url: str) -> tuple[str | None, str]:
    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Harvest/0.1"},
        trust_env=False,
    ) as client:
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
