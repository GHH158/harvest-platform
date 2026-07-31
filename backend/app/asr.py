from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


@dataclass(frozen=True)
class RecognizedWord:
    text: str
    start_ms: int
    end_ms: int


class ASRService:
    """DashScope file-transcription client.

    Fun-ASR uses an asynchronous submit/poll/result-download workflow. The
    implementation deliberately keeps the provider payload at this boundary so
    alignment can be tested without a cloud account.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def transcribe_words(self, audio_url: str) -> list[RecognizedWord]:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY 尚未配置；按 PROJECT.md §2.5 注册并配置后再处理任务。")

        base_url = self.settings.dashscope_base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.dashscope_asr_model,
            "input": {"file_urls": [audio_url]},
            "parameters": {"language_hints": ["ja"], "channel_id": [0]},
        }
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            submitted = client.post(
                f"{base_url}/services/audio/asr/transcription",
                headers={**headers, "X-DashScope-Async": "enable"},
                json=payload,
            )
            submitted.raise_for_status()
            task_id = str(submitted.json().get("output", {}).get("task_id", ""))
            if not task_id:
                raise RuntimeError("DashScope ASR 未返回 task_id。")

            deadline = time.monotonic() + self.settings.dashscope_asr_timeout_seconds
            while time.monotonic() < deadline:
                task = client.get(f"{base_url}/tasks/{task_id}", headers=headers)
                task.raise_for_status()
                output = task.json().get("output", {})
                task_status = str(output.get("task_status", ""))
                if task_status == "SUCCEEDED":
                    results = output.get("results") or []
                    if not results or results[0].get("subtask_status") != "SUCCEEDED":
                        message = (results[0].get("message") if results else None) or "未知子任务错误"
                        raise RuntimeError(f"DashScope ASR 子任务失败: {message}")
                    result_url = str(results[0].get("transcription_url", ""))
                    if not result_url:
                        raise RuntimeError("DashScope ASR 未返回 transcription_url。")
                    transcript = client.get(result_url)
                    transcript.raise_for_status()
                    return parse_words(transcript.json())
                if task_status in {"FAILED", "CANCELED", "CANCELLED"}:
                    raise RuntimeError(f"DashScope ASR 任务失败: {task_status}")
                time.sleep(self.settings.dashscope_asr_poll_seconds)
        raise RuntimeError("DashScope ASR 等待超时。")


def parse_words(payload: dict[str, Any]) -> list[RecognizedWord]:
    """Extract word timestamps from the documented Fun-ASR result JSON."""
    words: list[RecognizedWord] = []
    for transcript in payload.get("transcripts", []):
        for sentence in transcript.get("sentences", []):
            for word in sentence.get("words", []):
                value = str(word.get("text", "")).strip()
                if not value:
                    continue
                start_ms = int(word.get("begin_time", 0))
                end_ms = max(start_ms + 1, int(word.get("end_time", start_ms + 1)))
                words.append(RecognizedWord(text=value, start_ms=start_ms, end_ms=end_ms))
    if not words:
        raise RuntimeError("DashScope ASR 未返回词级时间戳。")
    return words
