from __future__ import annotations

import importlib.util
import math
import os
import re
import shutil
import subprocess
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

import httpx
import imageio_ffmpeg

from .config import Settings

VOICE_SEPARATION_MODEL = "htdemucs"


def voice_separation_available() -> bool:
    return all(importlib.util.find_spec(module) is not None for module in ("demucs", "numpy", "torch"))


def validate_video_voice_clip(start_seconds: float | None, duration_seconds: float) -> None:
    if not math.isfinite(duration_seconds):
        raise RuntimeError("视频片段时长必须是有限数字。")
    if start_seconds is not None and (not math.isfinite(start_seconds) or start_seconds < 0):
        raise RuntimeError("视频片段起点不能小于 0 秒。")
    if duration_seconds < 3 or duration_seconds > 30:
        raise RuntimeError("用于声音复刻的视频片段必须在 3–30 秒之间。")


@dataclass(frozen=True)
class ExtractedVoiceSample:
    path: Path
    mean_volume_db: float
    selected_start_seconds: float
    selected_duration_seconds: float
    quality_score: float
    active_ratio: float
    snr_db: float


@dataclass(frozen=True)
class ProbeRange:
    source_start_seconds: float
    output_start_seconds: float
    duration_seconds: float


@dataclass(frozen=True)
class ScoredWindow:
    source_start_seconds: float
    output_start_seconds: float
    duration_seconds: float
    score: float
    active_ratio: float
    snr_db: float


class VideoVoiceExtractor:
    """Find and isolate the clearest speech window for voice enrollment."""

    def __init__(self, data_dir: Path, *, timeout_seconds: int = 1_800) -> None:
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self.model = VOICE_SEPARATION_MODEL
        self.model_cache_dir = data_dir / "models" / "torch"
        self.timeout_seconds = timeout_seconds

    def extract(
        self,
        *,
        source: Path,
        work_directory: Path,
        start_seconds: float | None,
        duration_seconds: float,
    ) -> ExtractedVoiceSample:
        validate_video_voice_clip(start_seconds, duration_seconds)
        if not source.is_file():
            raise RuntimeError("视频声音复刻任务找不到原始视频。")
        if not voice_separation_available():
            raise RuntimeError("尚未安装本地人声分离组件；请运行 ./.venv/bin/pip install -e '.[voice]' 后重启 worker。")

        if work_directory.exists():
            shutil.rmtree(work_directory)
        work_directory.mkdir(parents=True, exist_ok=True)
        mixture, probe_ranges = self._prepare_mixture(
            source=source,
            work_directory=work_directory,
            start_seconds=start_seconds,
            duration_seconds=duration_seconds,
        )
        demucs_output = work_directory / "demucs"
        self._run_demucs(mixture, demucs_output)
        vocals = demucs_output / self.model / mixture.stem / "vocals.wav"
        if not vocals.is_file():
            candidates = list(demucs_output.rglob("vocals.wav"))
            if len(candidates) != 1:
                raise RuntimeError("人声分离完成但没有找到唯一的 vocals.wav 输出。")
            vocals = candidates[0]

        mono_vocals = work_directory / "vocals-mono.wav"
        self._run_ffmpeg(
            "-y",
            "-i",
            str(vocals),
            "-ac",
            "1",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(mono_vocals),
        )
        window = self._best_window(mono_vocals, probe_ranges, duration_seconds)
        sample = work_directory / "voice-sample.wav"
        self._run_ffmpeg(
            "-y",
            "-ss",
            f"{window.output_start_seconds:.3f}",
            "-t",
            f"{window.duration_seconds:.3f}",
            "-i",
            str(mono_vocals),
            "-af",
            "loudnorm=I=-18:TP=-2:LRA=11",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(sample),
        )
        mean_volume_db = self._mean_volume(sample)
        if mean_volume_db < -55:
            raise RuntimeError("所选片段没有检测到足够清晰的人声；请换到说话更连续、背景音乐更轻的片段。")
        return ExtractedVoiceSample(
            path=sample,
            mean_volume_db=mean_volume_db,
            selected_start_seconds=window.source_start_seconds,
            selected_duration_seconds=window.duration_seconds,
            quality_score=window.score,
            active_ratio=window.active_ratio,
            snr_db=window.snr_db,
        )

    def _prepare_mixture(
        self,
        *,
        source: Path,
        work_directory: Path,
        start_seconds: float | None,
        duration_seconds: float,
    ) -> tuple[Path, list[ProbeRange]]:
        media_duration = self._media_duration(source)
        if media_duration < 3:
            raise RuntimeError("视频中的音轨不足 3 秒，不能用于声音复刻。")
        if start_seconds is not None:
            if start_seconds >= media_duration:
                raise RuntimeError("手动片段起点已经超过视频时长。")
            available = min(duration_seconds, media_duration - start_seconds)
            if available < 3:
                raise RuntimeError("手动选择后剩余人声音轨不足 3 秒。")
            source_ranges = [(start_seconds, available)]
        else:
            source_ranges = self._automatic_probe_ranges(media_duration)

        probe_files: list[Path] = []
        probe_ranges: list[ProbeRange] = []
        output_start = 0.0
        for index, (source_start, probe_duration) in enumerate(source_ranges):
            probe_path = work_directory / f"probe-{index:02d}.wav"
            self._run_ffmpeg(
                "-y",
                "-ss",
                f"{source_start:.3f}",
                "-t",
                f"{probe_duration:.3f}",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "2",
                "-ar",
                "44100",
                "-c:a",
                "pcm_s16le",
                str(probe_path),
            )
            probe_files.append(probe_path)
            probe_ranges.append(ProbeRange(source_start, output_start, probe_duration))
            output_start += probe_duration

        mixture = work_directory / "selected.wav"
        if len(probe_files) == 1:
            shutil.copyfile(probe_files[0], mixture)
        else:
            arguments: list[str] = ["-y"]
            for probe_path in probe_files:
                arguments.extend(["-i", str(probe_path)])
            inputs = "".join(f"[{index}:a]" for index in range(len(probe_files)))
            arguments.extend(
                [
                    "-filter_complex",
                    f"{inputs}concat=n={len(probe_files)}:v=0:a=1[out]",
                    "-map",
                    "[out]",
                    "-c:a",
                    "pcm_s16le",
                    str(mixture),
                ]
            )
            self._run_ffmpeg(*arguments)
        return mixture, probe_ranges

    @staticmethod
    def _automatic_probe_ranges(media_duration: float) -> list[tuple[float, float]]:
        if media_duration <= 30:
            return [(0.0, media_duration)]
        count = min(8, max(2, math.ceil(media_duration / 30)))
        last_start = media_duration - 30
        starts = [round(index * last_start / (count - 1), 3) for index in range(count)]
        return [(start, 30.0) for start in starts]

    def _media_duration(self, source: Path) -> float:
        result = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-i", str(source)],
            capture_output=True,
            text=True,
            check=False,
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if match is None:
            raise RuntimeError("无法读取视频音轨时长。")
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    def _best_window(
        self,
        source: Path,
        probe_ranges: list[ProbeRange],
        requested_duration: float,
    ) -> ScoredWindow:
        with wave.open(str(source), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise RuntimeError("人声质量分析只支持 16-bit 单声道 WAV。")
            sample_rate = audio.getframerate()
            samples = array("h", audio.readframes(audio.getnframes()))
        if sys.byteorder == "big":
            samples.byteswap()
        frame_samples = max(1, round(sample_rate * 0.1))
        frame_db: list[float] = []
        frame_clipping: list[float] = []
        for offset in range(0, len(samples), frame_samples):
            frame = samples[offset : offset + frame_samples]
            if not frame:
                continue
            square_mean = sum(value * value for value in frame) / len(frame)
            rms = math.sqrt(square_mean) / 32768
            frame_db.append(20 * math.log10(max(rms, 1e-9)))
            frame_clipping.append(sum(abs(value) >= 32700 for value in frame) / len(frame))

        candidates: list[ScoredWindow] = []
        frame_seconds = frame_samples / sample_rate
        for probe in probe_ranges:
            window_duration = min(requested_duration, probe.duration_seconds, 29.5)
            if window_duration < 3:
                continue
            available_start = max(0.0, probe.duration_seconds - window_duration)
            offsets = [0.0] if available_start == 0 else [
                min(float(index), available_start) for index in range(math.ceil(available_start) + 1)
            ]
            offsets = list(dict.fromkeys(offsets))
            for local_start in offsets:
                output_start = probe.output_start_seconds + local_start
                first = max(0, math.floor(output_start / frame_seconds))
                last = min(len(frame_db), math.ceil((output_start + window_duration) / frame_seconds))
                levels = frame_db[first:last]
                if not levels:
                    continue
                ordered = sorted(levels)
                low = ordered[max(0, round((len(ordered) - 1) * 0.2))]
                high = ordered[max(0, round((len(ordered) - 1) * 0.8))]
                active_threshold = max(-45.0, low + 8.0)
                active_flags = [level >= active_threshold for level in levels]
                active_ratio = sum(active_flags) / len(active_flags)
                longest_run = 0
                current_run = 0
                for active in active_flags:
                    current_run = current_run + 1 if active else 0
                    longest_run = max(longest_run, current_run)
                continuity = longest_run / len(active_flags)
                clipping = sum(frame_clipping[first:last]) / len(levels)
                snr_db = max(0.0, high - low)
                if active_ratio < 0.25 or high < -48:
                    continue
                score = (
                    active_ratio * 50
                    + continuity * 30
                    + min(snr_db, 30)
                    + max(0.0, high + 50) * 0.5
                    - clipping * 1_000
                )
                candidates.append(
                    ScoredWindow(
                        source_start_seconds=probe.source_start_seconds + local_start,
                        output_start_seconds=output_start,
                        duration_seconds=window_duration,
                        score=round(score, 3),
                        active_ratio=round(active_ratio, 4),
                        snr_db=round(snr_db, 3),
                    )
                )
        if not candidates:
            raise RuntimeError("没有找到至少 3 秒且人声足够清晰的片段；请改用手动模式选择单人说话区段。")
        return max(candidates, key=lambda candidate: candidate.score)

    def _run_demucs(self, source: Path, output_directory: Path) -> None:
        self.model_cache_dir.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["TORCH_HOME"] = str(self.model_cache_dir)
        device = self._preferred_device()
        result = self._demucs_process(source, output_directory, device, environment)
        if result.returncode != 0 and device == "mps":
            result = self._demucs_process(source, output_directory, "cpu", environment)
        if result.returncode != 0:
            diagnostic = (result.stderr or result.stdout or "未知错误")[-1_500:]
            raise RuntimeError(f"Demucs 人声分离失败: {diagnostic}")

    def _demucs_process(
        self,
        source: Path,
        output_directory: Path,
        device: str,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "demucs.separate",
                    "--two-stems=vocals",
                    "--name",
                    self.model,
                    "--device",
                    device,
                    "--jobs",
                    "1",
                    "--out",
                    str(output_directory),
                    str(source),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"Demucs 人声分离超过 {self.timeout_seconds // 60} 分钟，任务已停止。") from error

    @staticmethod
    def _preferred_device() -> str:
        try:
            import torch

            if torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    def _mean_volume(self, source: Path) -> float:
        result = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-i", str(source), "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", result.stderr)
        if match is None:
            raise RuntimeError("分离结果是静音或无法读取有效音量。")
        return float(match.group(1))

    def _run_ffmpeg(self, *arguments: str) -> None:
        result = subprocess.run([self.ffmpeg, *arguments], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 无法准备声音复刻片段: {result.stderr[-1_000:]}")


def validate_voice_sample_duration(duration_ms: int) -> None:
    if duration_ms < 3_000 or duration_ms > 30_000:
        raise RuntimeError("声音复刻参考录音必须在 3–30 秒之间。")


class VoiceEnrollmentService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate_configuration(self) -> None:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY 尚未配置；声音复刻不会在未配置时调用云端。")

    def create_japanese_voice(self, *, audio_url: str, prefix: str) -> str:
        self.validate_configuration()
        normalized = re.sub(r"[^A-Za-z0-9]", "", prefix)[:10]
        if not normalized:
            raise RuntimeError("音色前缀至少需要一个英文字母或数字。")
        endpoint = f"{self.settings.dashscope_base_url.rstrip('/')}/services/audio/tts/customization"
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {self.settings.dashscope_api_key}"},
            json={
                "model": "voice-enrollment",
                "input": {
                    "action": "create_voice",
                    "target_model": self.settings.dashscope_tts_model,
                    "prefix": normalized,
                    "url": audio_url,
                    "language_hints": ["ja"],
                    "max_prompt_audio_length": 30,
                    "enable_preprocess": True,
                },
            },
            timeout=180.0,
            trust_env=False,
        )
        response.raise_for_status()
        voice_id = response.json().get("output", {}).get("voice_id")
        if not isinstance(voice_id, str) or not voice_id.strip():
            raise RuntimeError("百炼声音复刻没有返回 voice_id。")
        return voice_id.strip()
